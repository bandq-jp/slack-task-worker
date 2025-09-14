#!/bin/bash

# ローカル開発用起動スクリプト

echo "Starting FastAPI server..."
PYTHONPATH=$(pwd) uv run python src/main.py &
SERVER_PID=$!

echo "Server started with PID: $SERVER_PID"

# ngrokでトンネリング（別ターミナルで実行することを推奨）
echo ""
echo "Next steps:"
echo "1. Run 'ngrok http 8000' in another terminal"
echo "2. Copy the HTTPS URL from ngrok"
echo "3. Configure your Slack app with the following URLs:"
echo "   - Slash Commands: {ngrok-url}/slack/commands"
echo "   - Interactive Components: {ngrok-url}/slack/interactive"
echo ""
echo "Press Ctrl+C to stop the server"

# 終了処理
trap "kill $SERVER_PID" INT
wait $SERVER_PID