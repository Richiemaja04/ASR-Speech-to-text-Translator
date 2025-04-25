import queue
import sounddevice as sd
import vosk
import json
import asyncio
import requests
import websockets
import logging
import traceback
from aiohttp import web
import aiohttp_cors
from concurrent.futures import ThreadPoolExecutor
import sys
import os
import signal

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global state
active_connections = set()
audio_queue = queue.Queue()
executor = ThreadPoolExecutor(max_workers=3)
should_stop = asyncio.Event()

# Fix the file path format using raw string
MODEL_PATH = r"path of your vosk model"
try:
    vosk.SetLogLevel(-1)
    logger.info(f"Attempting to load Vosk model from {MODEL_PATH}")
    model = vosk.Model(MODEL_PATH)
    logger.info(f"Successfully loaded Vosk model")
except Exception as e:
    logger.error(f"Failed to load Vosk model: {str(e)}")
    logger.error(traceback.format_exc())
    sys.exit(1)

# Microsoft Translator API settings
# API key should be stored in environment variables or a secure config file
API_KEY = "api key"
REGION = "region"
ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

async def translate_text(text, target_lang="fr"):
    """Translate text using Microsoft Translator API with better error handling."""
    try:
        headers = {
            "Ocp-Apim-Subscription-Key": API_KEY,
            "Ocp-Apim-Subscription-Region": REGION,
            "Content-Type": "application/json"
        }
        params = {
            "api-version": "3.0",
            "to": target_lang
        }
        body = [{"text": text}]

        # Run the request in a thread pool to prevent blocking
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            executor,
            lambda: requests.post(ENDPOINT, params=params, headers=headers, json=body)
        )
        
        # Wait for the result with a timeout
        response = await asyncio.wait_for(future, timeout=5.0)
        
        if response.status_code == 200:
            return response.json()[0]["translations"][0]["text"]
        else:
            logger.error(f"Translation Error: {response.status_code}, {response.text}")
            return text  # Return original text if translation fails
    except asyncio.TimeoutError:
        logger.error("Translation request timed out")
        return text
    except Exception as e:
        logger.error(f"Translation exception: {str(e)}")
        logger.error(traceback.format_exc())
        return text  # Return original text on exception

def audio_callback(indata, frames, time, status):
    """Callback function to continuously capture audio."""
    if status:
        logger.warning(f"Audio status: {status}")
    audio_queue.put(bytes(indata))

async def process_audio(websocket, target_lang):
    """Process incoming audio and send transcription/translation to clients."""
    try:
        rec = vosk.KaldiRecognizer(model, 16000)
        current_partial = ""
        
        # Send initial status message
        status_msg = json.dumps({"type": "listening_started", "message": "Listening..."})
        await websocket.send_str(status_msg)
        logger.info(f"Sent listening_started message to client")
        
        while not should_stop.is_set():
            try:
                # Get audio data with timeout to allow for checking should_stop
                try:
                    data = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                    
                if rec.AcceptWaveform(data):
                    # Final result
                    result = json.loads(rec.Result())
                    text = result.get("text", "")
                    
                    if text:
                        # Log what we're sending
                        logger.info(f"Sending transcription: {text}")
                        
                        # Send transcription to client
                        transcription_msg = json.dumps({
                            "type": "transcription",
                            "text": text
                        })
                        await websocket.send_str(transcription_msg)
                        
                        # Translate asynchronously
                        translated_text = await translate_text(text, target_lang)
                        logger.info(f"Sending translation: {translated_text}")
                        
                        # Send translation to client
                        translation_msg = json.dumps({
                            "type": "translation",
                            "text": translated_text
                        })
                        await websocket.send_str(translation_msg)
                else:
                    # Partial result
                    partial = json.loads(rec.PartialResult())
                    partial_text = partial.get("partial", "")
                    
                    # Only send if partial text has changed
                    if partial_text and partial_text != current_partial:
                        current_partial = partial_text
                        partial_msg = json.dumps({
                            "type": "transcription",
                            "text": partial_text,
                            "partial": True
                        })
                        await websocket.send_str(partial_msg)
                        
            except Exception as e:
                logger.error(f"Error processing audio data: {str(e)}")
                logger.error(traceback.format_exc())
                # Don't break - try to continue processing
                await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"Fatal error in process_audio: {str(e)}")
        logger.error(traceback.format_exc())
    
    logger.info("Audio processing stopped")

async def websocket_handler(request):
    """Handle WebSocket connections."""
    ws = web.WebSocketResponse(heartbeat=30)  # Enable heartbeat to keep connection alive
    await ws.prepare(request)
    
    # Get target language from query parameters
    query = request.query
    target_lang = query.get("lang", "fr")
    
    logger.info(f"New WebSocket connection, target language: {target_lang}")
    
    # Add to active connections
    active_connections.add(ws)
    
    # Start audio stream if this is the first connection
    if len(active_connections) == 1:
        # Reset stop event
        should_stop.clear()
        
        # Start audio device in a separate task
        asyncio.create_task(start_audio_device())
    
    try:
        # Start audio processing for this client
        process_task = asyncio.create_task(process_audio(ws, target_lang))
        
        # Handle WebSocket messages (like stop commands)
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    logger.info(f"Received WebSocket message: {msg.data}")
                    data = json.loads(msg.data)
                    if data.get("command") == "stop":
                        break
                except json.JSONDecodeError:
                    logger.warning(f"Received invalid JSON: {msg.data}")
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {ws.exception()}")
                break
        
        # Cancel processing task
        process_task.cancel()
        try:
            await process_task
        except asyncio.CancelledError:
            pass
        
    finally:
        # Remove from active connections
        active_connections.remove(ws)
        
        # Stop audio device if no more connections
        if len(active_connections) == 0:
            should_stop.set()
            logger.info("No active connections, stopping audio capture")
    
    return ws

async def start_audio_device():
    """Start audio capture device with better error handling."""
    try:
        # Start audio stream
        stream = sd.RawInputStream(
            samplerate=16000,
            blocksize=4000,  # Smaller blocksize for lower latency
            dtype="int16",
            channels=1,
            callback=audio_callback
        )
        
        logger.info("Audio device started successfully")
        
        with stream:
            # Keep the stream running until should_stop is set
            while not should_stop.is_set():
                await asyncio.sleep(0.1)
                
        logger.info("Audio device stopped")
    except sd.PortAudioError as e:
        logger.error(f"PortAudio error: {str(e)}")
        logger.error(traceback.format_exc())
        logger.error("Check your audio device settings and make sure a microphone is connected")
    except Exception as e:
        logger.error(f"Error with audio device: {str(e)}")
        logger.error(traceback.format_exc())

async def index_handler(request):
    """Serve the frontend HTML."""
    try:
        return web.FileResponse('./index.html')
    except Exception as e:
        logger.error(f"Error serving index.html: {str(e)}")
        return web.Response(text="Error serving the frontend. Make sure index.html exists.", status=500)

async def on_shutdown(app):
    """Handle graceful shutdown."""
    should_stop.set()
    for ws in active_connections:
        await ws.close(code=1001, message=b"Server shutdown")
    logger.info("Closed all WebSocket connections during shutdown")

async def start_backend():
    """Initialize and start the web server with simplified initialization."""
    try:
        # Create web application
        app = web.Application()
        
        # Setup CORS with error handling
        try:
            cors = aiohttp_cors.setup(app, defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*"
                )
            })
            logger.info("CORS setup successful")
        except Exception as e:
            logger.error(f"CORS setup failed: {str(e)}")
            logger.error("Continuing without CORS support")
        
        # Add routes
        app.router.add_get('/ws', websocket_handler)
        app.router.add_get('/', index_handler)
        
        # Add static route for serving static files
        app.router.add_static('/static', './static', name='static')
        
        # Register shutdown handler
        app.on_shutdown.append(on_shutdown)
        
        # Apply CORS if available
        if 'cors' in locals():
            for route in list(app.router.routes()):
                try:
                    cors.add(route)
                except Exception as e:
                    logger.warning(f"Could not add CORS to route {route}: {e}")
        
        # Start the server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 5000)
        
        logger.info("Starting server at http://localhost:5000")
        await site.start()
        
        # Keep the server running
        while True:
            await asyncio.sleep(3600)  # 1 hour
            
    except Exception as e:
        logger.error(f"Failed to start backend: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def main():
    """Entry point for the application with enhanced error handling."""
    try:
        # Test audio devices before starting
        logger.info("Available audio devices:")
        try:
            devices = sd.query_devices()
            logger.info(f"Number of audio devices: {len(devices)}")
            for i, device in enumerate(devices):
                logger.info(f"Device {i}: {device['name']}")
        except Exception as e:
            logger.error(f"Error querying audio devices: {str(e)}")
        
        # Run the async event loop
        asyncio.run(start_backend())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        logger.info("Server shutdown complete")

if __name__ == "__main__":
    main()
