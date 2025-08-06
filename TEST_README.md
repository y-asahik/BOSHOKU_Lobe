# テスト用DI制御機能について

## 概要
app.pyにキーボードでDI1状態を疑似的に制御する機能を追加しました。

## テスト方法
1. アプリケーションを起動：`python app.py`
2. ライブビューウィンドウがアクティブな状態で操作：
   - **スペースキー**：DI1状態をON/OFFに切り替え
   - **qキー**：アプリケーション終了
3. コンソールに「Virtual DI1 status changed to: ON/OFF」と表示される

## 動作確認
- **DI1 OFF状態**：画面に「---」（グレー色）が表示され、判定処理は停止
- **DI1 ON状態**：1.5秒間隔で判定処理が実行され、OK/NGが表示される

## 元の実装に戻す方法
app.pyの以下の変更を元に戻してください：

### 1. 仮想DI状態の変数を削除またはコメントアウト（67行）
```python
# virtual_di1_status = False  # この行を削除またはコメントアウト
```

### 2. 関数のglobal宣言からvirtual_di1_statusを削除（173行）
```python
# 現在（テスト用）
global running, current_frame, last_judgment_time, is_focus_initialized, last_prediction, last_prediction_color, virtual_di1_status

# 元に戻す
global running, current_frame, last_judgment_time, is_focus_initialized, last_prediction, last_prediction_color
```

### 3. GPIO読み取りのコメントを外す（198～199行）
```python
# 現在（テスト用）
# di1_status = GPIO.input(DI1_PIN)  # 実際のGPIO読み取りをコメントアウト
di1_status = virtual_di1_status

# 元に戻す
di1_status = GPIO.input(DI1_PIN)  # コメントを外す
# di1_status = virtual_di1_status  # この行を削除またはコメントアウト
```

### 4. GPIO比較のコメントを外す（201行）
```python
# 現在（テスト用）
# if di1_status == GPIO.HIGH:  # 実際のGPIO比較をコメントアウト
if di1_status:  # テスト用：仮想DI状態で判定

# 元に戻す
if di1_status == GPIO.HIGH:  # コメントを外す
# if di1_status:  # この行を削除またはコメントアウト
```

### 5. スペースキーのハンドリングを削除（オプション）（274～277行）
```python
# この部分を削除またはコメントアウト
elif key == ord(' '):  # スペースキーでDI1状態を切り替え
    virtual_di1_status = not virtual_di1_status
    status_text = "ON" if virtual_di1_status else "OFF"
    print(f"Virtual DI1 status changed to: {status_text}")
```

## 注意事項
- テスト完了後は必ず元の実装に戻してください
- 実際のハードウェアテスト時は、DI1ピン（17番）に適切な信号を入力してください