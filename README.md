# Real-time Speech Translator

A web application that provides real-time speech transcription and translation using Python backend and a modern web frontend.

## Features

- Real-time speech recognition with Vosk
- Instant translation via Microsoft Translator API
- Support for multiple target languages
- User-friendly interface with visual feedback
- Responsive design that works on desktop and mobile devices

## Technologies Used

### Backend
- Python with asyncio for asynchronous processing
- aiohttp for WebSocket communication and web server
- Vosk for offline speech recognition
- sounddevice for audio capture
- Microsoft Translator API for language translation

### Frontend
- HTML5, CSS3, and JavaScript
- WebSocket for real-time communication
- Responsive design with modern animations

## Prerequisites

- Python 3.7+
- Vosk speech recognition model
- Microsoft Translator API key
- Required Python packages (see Installation)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/real-time-speech-translator.git
cd real-time-speech-translator
```

2. Install required Python packages:
```bash
pip install vosk sounddevice aiohttp aiohttp_cors websockets requests
```

3. Download a Vosk model from https://alphacephei.com/vosk/models and extract it to a directory.

4. Edit `app.py` and set:
   - `MODEL_PATH` to your Vosk model directory path
   - `API_KEY` to your Microsoft Translator API key
   - `REGION` to your Microsoft service region

## Usage

1. Start the backend server:
```bash
python app.py
```

2. Open a web browser and navigate to:
```
http://localhost:5000
```

3. Select your target translation language from the dropdown menu.

4. Click "Start Listening" to begin capturing and translating speech.

5. Speak clearly in English to see real-time transcription and translation.

6. Click "Stop Listening" when finished.

## Configuration

You can modify the following settings:

- **Target languages**: Edit the language options in `index.html` to add or remove supported languages.
- **Audio settings**: Adjust the sample rate and block size in `app.py` if needed.
- **Server port**: Change the port number in the `web.TCPSite` call in `app.py`.

## Troubleshooting

- **No sound input**: Check that your microphone is properly connected and has permissions.
- **Connection errors**: Ensure the Python backend is running and accessible.
- **Translation issues**: Verify your Microsoft Translator API key and region.
- **Performance problems**: Try a smaller Vosk model if speech recognition is slow.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [Vosk](https://github.com/alphacep/vosk-api) for providing the speech recognition engine
- Microsoft for the Translator API
- Contributors to the aiohttp and sounddevice libraries
