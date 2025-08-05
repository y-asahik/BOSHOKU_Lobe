import os
import RPi.GPIO as GPIO
from PIL import Image
from lobe import ImageModel
import cv2
import numpy as np
from datetime import datetime, time as dt_time
import subprocess
import time
import threading
import queue
from socket import *

# トリミング領域の指定 (左上x, 左上y, 幅, 高さ)
x, y, w, h = 195, 140, 200, 200

# GPIO設定（DO出力のみ使用）
DO1_PIN = 23
#DO2_PIN = 24
DI1_PIN = 17

GPIO.setmode(GPIO.BCM)  # GPIO番号でピンを指定
GPIO.setup(DO1_PIN, GPIO.OUT)
#GPIO.setup(DO2_PIN, GPIO.OUT)
GPIO.setup(DI1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# モデルを読み込む
model = ImageModel.load('path/to/exported/model/BOSHOKU TFLite')

# カメラの解像度を設定（1920x1080）
#subprocess.run(["v4l2-ctl", "--set-fmt-video=width=1920,height=1080,pixelformat=MJPG", "-d", "/dev/video0"])

# カメラの設定（OpenCV でカメラを開く）
camera = cv2.VideoCapture(0, cv2.CAP_V4L2)  # V4L2 モードで開く
#camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))  # MJPG を指定
#camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
#camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# ★ 追加：ライト点灯を確実にするためのダミーキャプチャ
ret, _ = camera.read()
if ret:
    print("ライト点灯確認済み（ダミーキャプチャ成功）")
    
# 確認
width = camera.get(cv2.CAP_PROP_FRAME_WIDTH)
height = camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
print(f"Camera resolution: {int(width)}x{int(height)}")

focus_value = 210

# 初回のみダミーキャプチャを実行するためのフラグ
is_focus_initialized = False

# 撮影回数カウンタ
capture_count = 0
# タイマー制御フラグ
running = True
# 設定
judgment_interval = 1.5  # 判定間隔（秒）

# グローバル変数
current_frame = None
last_judgment_time = 0
last_prediction = "初期化中"
last_prediction_color = (0, 0, 0)
# テスト用DI状態制御
virtual_di1_status = False  # テスト用の仮想DI1状態

# 非同期処理用キュー
frame_queue = queue.Queue(maxsize=2)
result_queue = queue.Queue()


# 初回撮影の前にフォーカスを調整するためのダミーキャプチャを実行する関数
def dummy_capture_to_adjust_focus():
    print("Performing dummy captures to adjust focus...")
    # オートフォーカスを無効にし、手動フォーカスを設定
    subprocess.run(["v4l2-ctl", "-d", "/dev/video0", "-c", "focus_automatic_continuous=0"])
    
    # フォーカスを手動で設定し、ダミーのキャプチャを複数回行うことでフォーカスを安定させる
    for i in range(3):  # 3回ダミーキャプチャを繰り返してフォーカスを安定させる
        subprocess.run(["v4l2-ctl", "-d", "/dev/video0", "-c", f"focus_absolute={focus_value}"])
        time.sleep(0.5)  # フォーカスが動作するまで待機
        ret, _ = camera.read()  # ダミーでフレームを読み込む
        if not ret:
            print(f"Dummy capture {i+1} failed")
        else:
            print(f"Dummy capture {i+1} successful")


# 非同期判定処理スレッド
def judgment_worker():
    global capture_count
    
    while running:
        try:
            # フレームを待機
            frame_data = frame_queue.get(timeout=1)
            if frame_data is None:
                break
                
            capture_count += 1
            
            # 撮影時間の取得
            start_time = time.time()
            now = datetime.now()
            datetime_text = now.strftime('%Y-%m-%d %H:%M:%S')
            
            print(f"--- {datetime_text} ---")
            print("Performing judgment...")
            
            # トリミング処理時間計測
            crop_start = time.time()
            cropped = frame_data[y:y + h, x:x + w]
            crop_time = time.time() - crop_start
            
            # PIL変換処理時間計測
            convert_start = time.time()
            img_pil = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
            convert_time = time.time() - convert_start
            
            # AI推論処理時間計測
            inference_start = time.time()
            result = model.predict(img_pil)
            inference_time = time.time() - inference_start
            
            total_time = time.time() - start_time
            
            print(f"Prediction: {result.prediction}")
            print(f"Processing times - Crop: {crop_time:.3f}s, Convert: {convert_time:.3f}s, Inference: {inference_time:.3f}s, Total: {total_time:.3f}s")
            
            # 結果をキューに送信
            result_data = {
                'prediction': result.prediction,
                'labels': result.labels
            }
            result_queue.put(result_data)
            
            for label, confidence in result.labels:
                print(f"{label}: {confidence*100}%")
                
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Error in judgment worker: {e}")
    
    print("Judgment thread: exiting while loop")

# GPIO制御処理
def process_judgment_result():
    global last_prediction, last_prediction_color
    
    try:
        result_data = result_queue.get_nowait()
        
        # 判定結果に応じてGPIO制御
        if result_data['prediction'] == 'OK':
            GPIO.output(DO1_PIN, GPIO.HIGH)
#            GPIO.output(DO2_PIN, GPIO.LOW)
            last_prediction_color = (255, 0, 0)  # 青色
            last_prediction = "OK"
        else :
            GPIO.output(DO1_PIN, GPIO.LOW)
#            GPIO.output(DO2_PIN, GPIO.HIGH)
            last_prediction = "NG"
            last_prediction_color = (0, 0, 255)  # 赤色
            
    except queue.Empty:
        pass  

# ライブビュー表示と判定を行う関数
def live_view_loop():
    global running, current_frame, last_judgment_time, is_focus_initialized, last_prediction, last_prediction_color, virtual_di1_status
    
    # 初回フォーカス調整
    if not is_focus_initialized:
        print("Initial setup...")
        dummy_capture_to_adjust_focus()
        is_focus_initialized = True
    
    while running:
        try:
            # フレーム取得
            ret, frame = camera.read()
            if not ret:
                print("Failed to grab frame")
                time.sleep(0.1)
                continue
            
            if not running:  # 追加チェック
                print("Live thread: running=False detected, breaking")
                break
                
            current_frame = frame
            current_time = time.time()
            
            # DI1の状態をチェック（テスト用：仮想DI状態を使用）
            # di1_status = GPIO.input(DI1_PIN)  # 実際のGPIO読み取りをコメントアウト
            di1_status = virtual_di1_status
            
            # if di1_status == GPIO.HIGH:  # 実際のGPIO比較をコメントアウト
            if di1_status:  # テスト用：仮想DI状態で判定
                # DI1がONの場合：判定処理を実行
                if current_time - last_judgment_time >= judgment_interval:
                    # フレームをキューに送信（ノンブロッキング）
                    try:
                        frame_queue.put_nowait(frame.copy())
                        last_judgment_time = current_time
                    except queue.Full:
                        # キューが満杯の場合は古いフレームを破棄
                        try:
                            frame_queue.get_nowait()
                            frame_queue.put_nowait(frame.copy())
                            last_judgment_time = current_time
                        except queue.Empty:
                            pass
                
                # 判定結果の処理
                process_judgment_result()
            else:
                # DI1がOFFの場合：判定停止、表示を"---"に設定
                last_prediction = "---"
                last_prediction_color = (128, 128, 128)  # グレー色
                GPIO.output(DO1_PIN, GPIO.LOW)  # GPIO出力もLOWに設定
            
            # 表示用画像作成
            cropped = frame[y:y + h, x:x + w]
            
            # 判定結果を画像に描画
            padding_height = 150
            bg_color = (255, 255, 255)
#            new_width = round(w * 1.5)
            new_width = round(w * 1.5)
            output_image = np.full((h + padding_height, new_width, 3), bg_color, dtype=np.uint8)
            
            start_x = (new_width - w) // 2
            output_image[padding_height:, start_x:start_x + w, :] = cropped
            
            # テキスト表示
            font_common = cv2.FONT_HERSHEY_SIMPLEX
            
            # 予測結果を表示
            text_size = cv2.getTextSize(last_prediction, font_common, 1, 2)[0]
            text_x = (new_width - text_size[0]) // 2
            text_y = padding_height // 3
            cv2.putText(output_image, last_prediction, (text_x, text_y),
                    font_common, 1, last_prediction_color, 2)
            
            # 日付と時間を表示
            now = datetime.now()
            date_text = now.strftime('%Y-%m-%d')
            time_text = now.strftime('%H:%M:%S')
            
            date_text_size = cv2.getTextSize(f"Date: {date_text}", font_common, 0.7, 1)[0]
            date_text_x = (new_width - date_text_size[0]) // 2
            date_text_y = text_y + 50
            cv2.putText(output_image, f"Date: {date_text}", (date_text_x, date_text_y),
                        font_common, 0.7, (0, 0, 0), 1)
            
            time_text_x = date_text_x
            time_text_y = date_text_y + 30
            cv2.putText(output_image, f"Time: {time_text}", (time_text_x, time_text_y),
                        font_common, 0.7, (0, 0, 0), 1)
            
            # 画面更新
            cv2.imshow('Prediction', output_image)
            
            # キーボード入力チェック
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("Live thread: 'q' key pressed")
                running = False
                break
            elif key == ord(' '):  # スペースキーでDI1状態を切り替え
                virtual_di1_status = not virtual_di1_status
                status_text = "ON" if virtual_di1_status else "OFF"
                print(f"Virtual DI1 status changed to: {status_text}")
                
            # ウィンドウが閉じられたかチェック
            try:
                window_prop = cv2.getWindowProperty('Prediction', cv2.WND_PROP_VISIBLE)
                if window_prop < 1:
                    print("Window closed by user")
                    running = False
                    break
            except cv2.error:
                print("Window closed (cv2.error)")
                running = False
                break
                
        except Exception as e:
            print(f"Error in live view loop: {e}")
            time.sleep(0.1)
    
    print("Live thread: exiting while loop")



# 判定処理スレッドを開始
judgment_thread = threading.Thread(target=judgment_worker, daemon=False)
judgment_thread.start()
print("Judgment worker thread started")

# ライブビュー＋判定スレッドを開始
live_thread = threading.Thread(target=live_view_loop, daemon=False)
live_thread.start()
print(f"Live view with judgment started (judgment interval: {judgment_interval}s)")

try:
    # プログラムが終了するまで待機
    import select
    import sys
    
    print("Press enter to quit (or 'q' in video window)")
    while running:
        # ノンブロッキング入力チェック
        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
        if ready:
            input()  # Enter押下を検出
            break
        # runningがFalseになったら終了
        if not running:
            break
    
    print("Shutting down...")
    running = False

finally:
    print("Cleaning up resources...")
    running = False
    
    # 短時間待機してスレッドが自然終了するのを待つ
    time.sleep(0.5)
    
    # リソース解放
    try:
        cv2.destroyAllWindows()
        print("Windows destroyed")
    except:
        pass
    
    try:
        camera.release()
        print("Camera released")
    except:
        pass
    
    try:
        GPIO.cleanup()
        print("GPIO cleaned up")
    except:
        pass
    
    print("Application terminated")
    
    # 強制終了
    import sys
    sys.exit(0)
