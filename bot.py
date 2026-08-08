import os
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import PyPDF2
import docx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest
from google import genai

# Load environment variables from .env file
load_dotenv()

# Read secret tokens safely from system memory
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Google Gemini AI client
client = genai.Client(api_key=GEMINI_KEY)

# Dictionary to store conversation history for each user
user_memory = {}

# System instructions defining AI behavior
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
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    # Render explicitly passes PORT=10000 into the environment
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Health server listening on port {port}...")
    server.serve_forever()

# Handler function to process regular text messages
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

# Handler function to process uploaded files (PDFs and DOCX)
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("Document received! Downloading and extracting financial metrics...")
    
    try:
        document = update.message.document
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()

        extracted_text = ""
        file_name = document.file_name.lower() if document.file_name else ""

        if file_name.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            for page in pdf_reader.pages:
                extracted_text += page.extract_text() or ""
            extracted_text = extracted_text[:4000]

        elif file_name.endswith('.docx') or file_name.endswith('.doc'):
            doc = docx.Document(io.BytesIO(file_bytes))
            for para in doc.paragraphs:
                extracted_text += para.text + "\n"
            extracted_text = extracted_text[:4000]

        else:
            extracted_text = file_bytes.decode('utf-8', errors='ignore')[:4000]

        if not extracted_text.strip():
            extracted_text = "Standard financial report file attached."

        prompt = f"{SYSTEM_PROMPT}\nAnalyze this uploaded financial document and summarize key financial metrics, revenues, risks, or performance concisely:\n\n{extracted_text}"

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )
        await status_msg.edit_text(response.text)

    except Exception as e:
        print(f"Terminal Log -> Document error: {e}")
        await status_msg.edit_text("Sorry, I encountered an error downloading or parsing that document. Please try re-uploading a standard PDF or DOCX file.")

# Main program entry point
if __name__ == '__main__':
    # Start internal web server on background thread for Render port check
    threading.Thread(target=run_health_server, daemon=True).start()

    # Extended 120-second timeout for large document transfers
    request = HTTPXRequest(connect_timeout=120.0, read_timeout=120.0)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).request(request).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Atlas AI Financial Assistant Bot is live and listening...")
    app.run_polling()