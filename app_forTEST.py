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

# GPIO設定
DI1_PIN = 17
DI2_PIN = 27
DO1_PIN = 23
DO2_PIN = 24

#GPIO.setmode(GPIO.BCM)  # GPIO番号でピンを指定
#GPIO.setup(DI1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
#GPIO.setup(DI2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
#GPIO.setup(DO1_PIN, GPIO.OUT)
#GPIO.setup(DO2_PIN, GPIO.OUT)

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

# 前回の日次リネーム時刻を記録する変数
last_daily_rename = None

# CSVファイルのパス
csv_path = 'predictions.csv'

# CSVファイルにデータを追加する関数
def append_to_csv(prediction_text, labels, datetime_text):
    
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
    subprocess.run(["v4l2-ctl", "-d", "/dev/video0", "-c", "focus_automatic_continuous=0"])
    
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

# 写真を撮影して判定する関数
#def capture_and_predict(channel):
def capture_and_predict():    # for test
    global is_focus_initialized
    global capture_count
    capture_count += 1

    # 初回のみフォーカスを調整するためのダミーキャプチャを実行(for ArduCAM)
    print(is_focus_initialized)
    if not is_focus_initialized:
        dummy_capture_to_adjust_focus()
        is_focus_initialized = True  # フラグを立てて次回以降はダミーキャプチャを行わない
        
    # 撮影時間の取得
    now = datetime.now()
    datetime_text = now.strftime('%Y-%m-%d %H:%M:%S')
    datetime_img = now.strftime('%Y-%m-%d %H%M%S')
    date_text = now.strftime('%Y-%m-%d')
    time_text = now.strftime('%H:%M:%S')
    
    print(f"--- {datetime_text} ---")
    print("Taking picture...")
    # バッファ内の古いフレームを破棄
    subprocess.run(["v4l2-ctl", "-d", "/dev/video0", "-c", f"focus_absolute={focus_value}"])
    for _ in range(5):  # 5は任意の数です。バッファサイズに応じて調整してください
        camera.grab()
    
    ret, frame = camera.read()
    if not ret:
        print("Failed to grab frame")
        return

    img = frame
    # トリミング
    cropped = img[y:y + h, x:x + w]
    cv2.imwrite('image.jpg', cropped)

    # PIL.Imageオブジェクトに変換し、モデルに渡す前に必要な場合はさらに前処理
    img_pil = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
    result = model.predict(img_pil)
    
    prediction_value = result.prediction
    print(f"Prediction: {result.prediction}")

    # 判定結果に応じてを制御
    if result.prediction == 'OK':
#        GPIO.output(DO1_PIN, GPIO.HIGH)
#        GPIO.output(DO2_PIN, GPIO.LOW)
        text_color = (255, 0, 0)  # 青色
        prediction_text = "OK"
        # 判定がUnCutかOverCutの場合、NGとする
    elif result.prediction == 'Untap':
#        GPIO.output(DO1_PIN, GPIO.LOW)
#        GPIO.output(DO2_PIN, GPIO.HIGH)
        prediction_text = "UnTap"
        text_color = (0, 0, 255)  # 赤色
    elif result.prediction == 'NoHole':
#        GPIO.output(DO1_PIN, GPIO.LOW)
#        GPIO.output(DO2_PIN, GPIO.HIGH)
        prediction_text = "NoHole"
        text_color = (0, 0, 255)  # 赤色
#NGの画像を保存
#        file_path = os.path.join(img_dir, f"image_{capture_count}.jpg")
#        cv2.imwrite(file_path, cropped)
#        print(f"Image saved as {file_path}")  
        
    # CSVファイルに結果を追加
    append_to_csv(prediction_text, result.labels, datetime_text)
            
    for label, confidence in result.labels:
        print(f"{label}: {confidence*100}%")

    # - 判定結果を画像に描画 -
    padding_height = 150  # 余白の高さ
    bg_color = (255, 255, 255)  # 背景の色（B,G,R）:白色

    new_width = round(w * 1.5)
    output_image = np.full((h + padding_height, new_width, 3), bg_color, dtype=np.uint8)

    start_x = (new_width - w) // 2
    output_image[padding_height:, start_x:start_x + w, :] = cropped

    # -- テキストの表示 --
    font_common = cv2.FONT_HERSHEY_SIMPLEX  # フォントの設定

    # --- 予測結果を表示 ---
    text_size = cv2.getTextSize(prediction_text, font_common, 1, 2)[0]
    # 中央配置用にx座標を計算（new_widthを使う）
    text_x = (new_width - text_size[0]) // 2
    text_y = padding_height // 3
    # テキストを描画
    cv2.putText(output_image, prediction_text, (text_x, text_y),
            font_common, 1, text_color, 2)

    # --- 日付と時間を表示---
    date_text_size = cv2.getTextSize(f"Date: {date_text}", font_common, 0.7, 1)[0]
    date_text_x = (new_width - date_text_size[0]) // 2
    date_text_y = text_y + 50
    cv2.putText(output_image, f"Date: {date_text}", (date_text_x, date_text_y),
                font_common, 0.7, (0, 0, 0), 1)

    time_text_size = cv2.getTextSize(f"Time: {time_text}", font_common, 0.7, 1)[0]
    time_text_x = date_text_x    # Dateと左側の位置を揃えるためdate_text_sizeを使う
    # time_text_x = (new_width - time_text_size[0]) // 2  # 中央揃えしたいならこっちを使う
    time_text_y = date_text_y + 30
    cv2.putText(output_image, f"Time: {time_text}", (time_text_x, time_text_y),
                font_common, 0.7, (0, 0, 0), 1)

    cv2.imshow('Prediction', output_image)
    cv2.waitKey(1000)

    # 10回に1回の画像を保存
#    if capture_count % 10 == 0:
#    file_path = os.path.join(img_dir, f"image_{capture_count}_{prediction_text}.jpg")

    # 画像保存前にディレクトリが存在するか確認
    os.makedirs(img_dir, exist_ok=True)

    file_path = os.path.join(img_dir, f"image_{capture_count:05d}_{prediction_text}_{datetime_img}.jpg")
    cv2.imwrite(file_path, cropped)
    print(f"Image saved as {file_path}")  

# DOをリセットする関数
def reset_do(channel):
    statusDO1 = GPIO.input(DO1_PIN)
    statusDO2 = GPIO.input(DO2_PIN)
    print(f"GPIO_DO1_STATUS:PIN{DO1_PIN}:{statusDO1}")
    print(f"GPIO_DO2_STATUS:PIN{DO2_PIN}:{statusDO2}")
    print("Resetting DO pins...")
    GPIO.output(DO1_PIN, GPIO.LOW)
    GPIO.output(DO2_PIN, GPIO.LOW)
    statusDO1 = GPIO.input(DO1_PIN)
    statusDO2 = GPIO.input(DO2_PIN)
    print(f"GPIO_DO1_ResetSTATUS:PIN{DO1_PIN}:{statusDO1}")
    print(f"GPIO_DO2_ResetSTATUS:PIN{DO2_PIN}:{statusDO2}")

# イベント検出の設定
#GPIO.add_event_detect(DI1_PIN, GPIO.RISING, callback=capture_and_predict, bouncetime=5000)
#GPIO.add_event_detect(DI2_PIN, GPIO.RISING, callback=reset_do, bouncetime=5000)

# プログラム起動時に日次リネームをチェック
daily_rename()

# 日次リネームチェック用のスレッドを開始
daily_rename_thread = threading.Thread(target=check_daily_rename, daemon=True)
daily_rename_thread.start()
print("Daily rename checker started")

try:
    # プログラムが終了するまで待機
    message = input("Press enter to quit\n\n")

    while True:
        command = input("Enter 'd' to capture and predict, 'r' to reset DO, or 'q' to exit: ")
        if command == 'd':
            capture_and_predict()
        elif command == 'r':
            reset_do()
        elif command == 'q':
            break

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
