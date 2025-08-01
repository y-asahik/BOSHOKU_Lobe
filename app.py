import os
import csv
import RPi.GPIO as GPIO
#from time import sleep
from PIL import Image
from lobe import ImageModel
import cv2
import numpy as np
from datetime import datetime, time as dt_time
import subprocess
import time
import threading
from socket import *

# トリミング領域の指定 (左上x, 左上y, 幅, 高さ)
x, y, w, h = 480, 300, 400, 400

# GPIO設定（DO出力のみ使用）
DO1_PIN = 23
DO2_PIN = 24

GPIO.setmode(GPIO.BCM)  # GPIO番号でピンを指定
GPIO.setup(DO1_PIN, GPIO.OUT)
GPIO.setup(DO2_PIN, GPIO.OUT)

# 画像を保存するフォルダを作成
img_dir = "img"
os.makedirs(img_dir, exist_ok=True)

# モデルを読み込む
model = ImageModel.load('path/to/exported/model/CASE0241_Tap TFLite')

# カメラの解像度を設定（1920x1080）
subprocess.run(["v4l2-ctl", "--set-fmt-video=width=1920,height=1080,pixelformat=MJPG", "-d", "/dev/video0"])

# カメラの設定
#camera = cv2.VideoCapture(0)  # 通常、0はデフォルトのカメラを指します
# 高解像度に設定

# OpenCV でカメラを開く
camera = cv2.VideoCapture(0, cv2.CAP_V4L2)  # V4L2 モードで開く
camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))  # MJPG を指定
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# ★ 追加：ライト点灯を確実にするためのダミーキャプチャ
ret, _ = camera.read()
if ret:
    print("ライト点灯確認済み（ダミーキャプチャ成功）")
    
# 確認
width = camera.get(cv2.CAP_PROP_FRAME_WIDTH)
height = camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
print(f"Camera resolution: {int(width)}x{int(height)}")

focus_value = 572

# 初回のみダミーキャプチャを実行するためのフラグ
is_focus_initialized = False

# 撮影回数カウンタ
capture_count = 0
# 保存用カウンタ
save_count = 0
# 最後の保存時刻
last_save_time = time.time()
# タイマー制御フラグ
running = True
# 設定
judgment_interval = 1.0  # 判定間隔（秒）
save_interval = 10   # 保存間隔（秒）
enable_image_save = False  # 画像保存ON/OFF
enable_csv_output = False  # CSV出力ON/OFF

# グローバル変数
current_frame = None
last_judgment_time = 0
last_prediction = "初期化中"
last_prediction_color = (0, 0, 0)

# 前回の日次リネーム時刻を記録する変数
last_daily_rename = None

# CSVファイルのパス
csv_path = 'predictions.csv'

# CSVファイルにデータを追加する関数
def append_to_csv(prediction_text, labels, datetime_text):
    # CSVファイルのパス
#    csv_path = 'predictions.csv'
    
    # ヘッダーを定義（ファイルが新規作成される場合にのみ使用）
    headers = ['DateTime', 'Prediction', 'Label', 'Confidence']

    # ファイルが存在しない場合はヘッダーを追加
    try:
        with open(csv_path, 'x', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(headers)
    except FileExistsError:
        pass  # ファイルが存在する場合は何もしない

    # データをCSVファイルに書き込む
    with open(csv_path, 'a', newline='') as file:
        writer = csv.writer(file)
        # 各ラベルと信頼度について行を追加
        for label, confidence in labels:
            writer.writerow([datetime_text, prediction_text, label, confidence * 100])


# 初回撮影の前にフォーカスを調整するためのダミーキャプチャを実行する関数
def dummy_capture_to_adjust_focus():
    print("Performing dummy captures to adjust focus...")
    # オートフォーカスを無効にし、手動フォーカスを設定
    subprocess.run(["v4l2-ctl", "-d", "/dev/video0", "-c", "focus_auto=0"])
    
    # フォーカスを手動で設定し、ダミーのキャプチャを複数回行うことでフォーカスを安定させる
    for i in range(3):  # 10回ダミーキャプチャを繰り返してフォーカスを安定させる
        subprocess.run(["v4l2-ctl", "-d", "/dev/video0", "-c", f"focus_absolute={focus_value}"])
        time.sleep(0.5)  # フォーカスが動作するまで待機
        ret, _ = camera.read()  # ダミーでフレームを読み込む
        if not ret:
            print(f"Dummy capture {i+1} failed")
        else:
            print(f"Dummy capture {i+1} successful")

# 日次リネーム処理を行う関数
def daily_rename():
    global last_daily_rename
    global capture_count
    
    # 現在時刻を取得
    now = datetime.now()
    current_time = now.time()
    target_time = dt_time(8, 0)  # 朝8時
    
    # 今日の日付
    today = now.date()
    
    # 前回実行した日付と比較して、今日まだ実行していない場合のみ実行
    if (last_daily_rename is None or last_daily_rename != today) and current_time >= target_time:
        print("Starting daily rename process...")
        
        # タイムスタンプの生成
        timestamp = now.strftime('%Y%m%d_%H%M')
        
        # imgフォルダをリネーム
        if os.path.exists(img_dir) and os.path.isdir(img_dir):
            new_img_dir = f"{img_dir}_{timestamp}"
            os.rename(img_dir, new_img_dir)
            print(f"Folder renamed to {new_img_dir}")
            
            # 新しいimgフォルダを作成
            os.makedirs(img_dir, exist_ok=True)
            print(f"New {img_dir} folder created")
        
        # predictions.csvをリネーム
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
            new_csv = f"predictions_{timestamp}.csv"
            os.rename(csv_path, new_csv)
            print(f"CSV file renamed to {new_csv}")
        
        # イメージファイルカウンタをリセット
        capture_count = 0
        print("Image counter reset to 0")
        
        # 実行日付を記録
        last_daily_rename = today
        print("Daily rename process completed")

# 定期的に日次リネームをチェックする関数
def check_daily_rename():
    while True:
        daily_rename()
        time.sleep(60)  # 1分間隔でチェック

# 判定処理を行う関数
def perform_judgment():
    global capture_count, save_count, last_save_time, last_prediction, last_prediction_color, current_frame
    
    if current_frame is None:
        return
        
    capture_count += 1
    current_time = time.time()
    should_save = (current_time - last_save_time) >= save_interval
    
    # 撮影時間の取得
    now = datetime.now()
    datetime_text = now.strftime('%Y-%m-%d %H:%M:%S')
    datetime_img = now.strftime('%Y-%m-%d %H%M%S')
    
    print(f"--- {datetime_text} ---")
    print("Performing judgment...")
    
    # トリミング
    cropped = current_frame[y:y + h, x:x + w]
    
    # PIL.Imageオブジェクトに変換し、モデルに渡す前に必要な場合はさらに前処理
    img_pil = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
    result = model.predict(img_pil)
    
    print(f"Prediction: {result.prediction}")

    # 判定結果に応じてGPIO制御
    if result.prediction == 'OK':
        GPIO.output(DO1_PIN, GPIO.HIGH)
        GPIO.output(DO2_PIN, GPIO.LOW)
        last_prediction_color = (255, 0, 0)  # 青色
        last_prediction = "OK"
    elif result.prediction == 'Untap':
        GPIO.output(DO1_PIN, GPIO.LOW)
        GPIO.output(DO2_PIN, GPIO.HIGH)
        last_prediction = "UnTap"
        last_prediction_color = (0, 0, 255)  # 赤色
    elif result.prediction == 'NoHole':
        GPIO.output(DO1_PIN, GPIO.LOW)
        GPIO.output(DO2_PIN, GPIO.HIGH)
        last_prediction = "NoHole"
        last_prediction_color = (0, 0, 255)  # 赤色
        
    # CSVファイルに結果を追加（設定で有効になっている場合のみ）
    if enable_csv_output and should_save:
        append_to_csv(last_prediction, result.labels, datetime_text)
    
    # 画像保存（設定で有効になっており、保存間隔に達している場合のみ）
    if enable_image_save and should_save:
        os.makedirs(img_dir, exist_ok=True)
        save_count += 1
        file_path = os.path.join(img_dir, f"image_{save_count:05d}_{last_prediction}_{datetime_img}.jpg")
        cv2.imwrite(file_path, cropped)
        print(f"Image saved as {file_path}")
        last_save_time = current_time
        
    for label, confidence in result.labels:
        print(f"{label}: {confidence*100}%")  

# ライブビュー表示と判定を行う関数
def live_view_loop():
    global running, current_frame, last_judgment_time, is_focus_initialized
    
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
                
            current_frame = frame
            current_time = time.time()
            
            # 判定タイミングかチェック
            if current_time - last_judgment_time >= judgment_interval:
                perform_judgment()
                last_judgment_time = current_time
            
            # 表示用画像作成
            cropped = frame[y:y + h, x:x + w]
            
            # 判定結果を画像に描画
            padding_height = 150
            bg_color = (255, 255, 255)
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
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
        except Exception as e:
            print(f"Error in live view loop: {e}")
            time.sleep(0.1)


# プログラム起動時に日次リネームをチェック
daily_rename()

# 日次リネームチェック用のスレッドを開始
daily_rename_thread = threading.Thread(target=check_daily_rename, daemon=True)
daily_rename_thread.start()
print("Daily rename checker started")

# ライブビュー＋判定スレッドを開始
live_thread = threading.Thread(target=live_view_loop, daemon=True)
live_thread.start()
print(f"Live view with judgment started (judgment interval: {judgment_interval}s, save interval: {save_interval}s)")
print(f"Image save: {'enabled' if enable_image_save else 'disabled'}, CSV output: {'enabled' if enable_csv_output else 'disabled'}")

try:
    # プログラムが終了するまで待機
    message = input("Press enter to quit (or 'q' in video window)\n\n")
    running = False

#    while True:
#        command = input("Enter 'd' to capture and predict, 'r' to reset DO, or 'q' to exit: ")
#        if command == 'd':
#            capture_and_predict()
#        elif command == 'r':
#            reset_do()
#        elif command == 'q':
#            break

finally:
    camera.release()
    cv2.destroyAllWindows()
    GPIO.cleanup()

    # 終了時刻の取得
    now = datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M')

    # imgフォルダをリネーム
    new_img_dir = f"{img_dir}_{timestamp}"
    if os.path.exists(img_dir) and os.path.isdir(img_dir):
        os.rename(img_dir, new_img_dir)
        print(f"フォルダを {new_img_dir} に変更しました")

    # predictions.csv をリネーム
    if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        new_csv = f"predictions_{timestamp}.csv"
        os.rename(csv_path, new_csv)
        print(f"CSVファイルを {new_csv} に変更しました")
    else:
        print("CSVファイルが存在しないか空のため、リネームをスキップしました")
