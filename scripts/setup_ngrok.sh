#!/bin/bash

# ngrokのインストールスクリプト

echo "Installing ngrok..."

if command -v ngrok &> /dev/null; then
    echo "ngrok is already installed"
else
    # Linux/WSL用のインストール
    if [ "$(uname)" == "Linux" ]; then
        curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | \
            sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && \
            echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | \
            sudo tee /etc/apt/sources.list.d/ngrok.list && \
            sudo apt update && sudo apt install ngrok
    # macOS用のインストール
    elif [ "$(uname)" == "Darwin" ]; then
        if command -v brew &> /dev/null; then
            brew install ngrok
        else
            echo "Please install Homebrew first or download ngrok from https://ngrok.com/download"
        fi
    fi
fi

echo "ngrok installation complete!"
echo ""
echo "Next steps:"
echo "1. Sign up for a free ngrok account at https://ngrok.com"
echo "2. Get your authtoken from the dashboard"
echo "3. Run: ngrok config add-authtoken <your-authtoken>"
echo "4. Start ngrok with: ngrok http 8000"