import os
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import PyPDF2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai

# Load environment variables from the .env file
load_dotenv()

# Read the secret tokens safely from system memory
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the Google Gemini AI client
client = genai.Client(api_key=GEMINI_KEY)

# Dictionary to store conversation history for each user
user_memory = {}

# System instructions to define the AI's role and rules
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
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Handler function to process regular text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id  # Get unique ID of the user
    user_text = update.message.text     # Get the message text sent by the user

    # If this is a new user, create a blank history list for them
    if user_id not in user_memory:
        user_memory[user_id] = []
    
    # Get the last 4 messages from history to maintain context
    recent_context = "\n".join(user_memory[user_id][-4:]) if user_memory[user_id] else "No prior history."

    # Combine instructions, chat history, and the new question
    full_prompt = f"{SYSTEM_PROMPT}\n\nRecent History Context:\n{recent_context}\n\nUser Question: {user_text}"

    try:
        # Using official stable production model name
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt
        )
        reply = response.text  # Extract the text answer from the AI response
        
        # Save this exchange into memory for the next message turn
        user_memory[user_id].append(f"User: {user_text}")
        user_memory[user_id].append(f"Atlas: {reply}")
        
        # Send the response back to the user on Telegram
        await update.message.reply_text(reply)
        
    except Exception as e:
        print(f"Terminal Log -> Text error: {e}")  # Print error in terminal for debugging
        await update.message.reply_text("Apologies, I encountered an issue analyzing your request.")

# Handler function to process uploaded files (PDFs)
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Document received. Analyzing financial data...")
    
    document = update.message.document                 # Get document info
    file = await context.bot.get_file(document.file_id) # Get file download path
    file_bytes = await file.download_as_bytearray()     # Download file as raw bytes

    extracted_text = ""
    
    # Check if the uploaded file is a PDF
    if document.file_name and document.file_name.lower().endswith('.pdf'):
        try:
            # Read the PDF bytes from memory
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            
            # Extract text from every page of the PDF
            for page in pdf_reader.pages:
                extracted_text += page.extract_text() or ""
                
            # Keep only the first 3000 characters to keep processing fast
            extracted_text = extracted_text[:3000] 
        except Exception as read_err:
            print(f"Terminal Log -> PDF error: {read_err}")
            extracted_text = "Error parsing file contents."
    else:
        extracted_text = "Standard financial document structure attached."

    # Create the analysis prompt with the extracted text
    prompt = f"{SYSTEM_PROMPT}\nAnalyze this uploaded financial document and summarize key financial metrics, revenues, risks, or performance concisely:\n\n{extracted_text}"

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        print(f"Terminal Log -> Document error: {e}")
        await update.message.reply_text("Error processing document contents.")

# Main program entry point
if __name__ == '__main__':
    # Start internal background thread for Render free web service health check
    threading.Thread(target=run_health_server, daemon=True).start()

    # Build the Telegram application with the token
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Register text handler (handles text but ignores commands like /start)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # Register document handler (handles files like PDFs)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Atlas AI Financial Assistant Bot is live and listening...")
    
    # Start checking Telegram servers continuously for new messages
    app.run_polling()