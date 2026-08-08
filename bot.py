import os
import io
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import PyPDF2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest
from google import genai

# Load environment variables from .env file (for local testing only.
# On Render, set these in Dashboard -> Environment instead.)
load_dotenv()

# Read secret keys safely from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Fail loudly and clearly if secrets are missing, instead of crashing
# with a confusing traceback deep inside python-telegram-bot.
if not TELEGRAM_TOKEN:
    print("FATAL: TELEGRAM_BOT_TOKEN is not set. Add it in Render -> Environment.")
    sys.exit(1)
if not GEMINI_KEY:
    print("FATAL: GEMINI_API_KEY is not set. Add it in Render -> Environment.")
    sys.exit(1)

# Initialize Gemini AI client
client = genai.Client(api_key=GEMINI_KEY)

# Chat memory context storage per user ID
user_memory = {}

SYSTEM_PROMPT = """
You are Atlas, a personal AI Financial Assistant built specifically for finance professionals.
Guidelines:
1. Provide short, concise, highly readable, and actionable insights (under 150 words). Avoid dense walls of text.
2. Remember user context (their role, stocks, sectors, or topics they monitor).
3. Analyze financial queries, stock data, uploaded PDFs, or financial spreadsheet text cleanly.
4. Maintain a natural, conversational tone without requiring rigid commands.
"""

# Dummy HTTP server handler to satisfy Render's Free Web Service port check
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Atlas Bot is Live!")

    # Silence default request logging so Render logs stay readable
    def log_message(self, format, *args):
        pass

def run_health_server():
    # Render explicitly passes PORT into environment (defaults to 10000 locally)
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Health server listening on port {port}...")
    server.serve_forever()

# Handler function to process incoming text questions
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_memory:
        user_memory[user_id] = []

    recent_context = "\n".join(user_memory[user_id][-4:]) if user_memory[user_id] else "No prior history."
    full_prompt = f"{SYSTEM_PROMPT}\n\nRecent History Context:\n{recent_context}\n\nUser Question: {user_text}"

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=full_prompt
        )
        reply = response.text

        user_memory[user_id].append(f"User: {user_text}")
        user_memory[user_id].append(f"Atlas: {reply}")

        await update.message.reply_text(reply)

    except Exception as e:
        print(f"Terminal Log -> Text error: {e}")
        await update.message.reply_text("Apologies, I encountered an issue analyzing your request.")

# Handler function to process uploaded PDF documents
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Document received. Analyzing financial data...")

    document = update.message.document
    file = await context.bot.get_file(document.file_id)
    file_bytes = await file.download_as_bytearray()

    extracted_text = ""

    if document.file_name and document.file_name.lower().endswith('.pdf'):
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            for page in pdf_reader.pages:
                extracted_text += page.extract_text() or ""
            extracted_text = extracted_text[:3000]
        except Exception as read_err:
            print(f"Terminal Log -> PDF error: {read_err}")
            extracted_text = "Error parsing file contents."
    else:
        extracted_text = "Standard financial document structure attached."

    prompt = f"{SYSTEM_PROMPT}\nAnalyze this uploaded financial document and summarize key financial metrics, revenues, risks, or performance concisely:\n\n{extracted_text}"

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        print(f"Terminal Log -> Document error: {e}")
        await update.message.reply_text("Error processing document contents.")

if __name__ == '__main__':
    # Start internal web server on background thread for Render's port check
    threading.Thread(target=run_health_server, daemon=True).start()

    # Set custom 60-second timeout for downloading PDFs/requests
    request = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Atlas AI Financial Assistant Bot is live and listening...")
    app.run_polling()
