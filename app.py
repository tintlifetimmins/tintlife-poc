from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncOpenAI
import os

app = FastAPI()

# Connect to Database
mongo_url = os.environ.get("MONGO_URI")
client = AsyncIOMotorClient(mongo_url)
db = client.tintlife
prices_collection = db.prices

# Connect to Groq (Free, no card)
groq_key = os.environ.get("GROQ_API_KEY")
ai_client = AsyncOpenAI(
    api_key=groq_key,
    base_url="https://api.groq.com/openai/v1"
)

# --- 1. LOAD THE PRICE LIST ---
@app.on_event("startup")
async def load_prices():
    count = await prices_collection.count_documents({})
    if count == 0:
        prices = [
            {"service": "Full 4 door Sedan", "price": 350},
            {"service": "Full 2 door Coupe", "price": 325},
            {"service": "Full small SUV", "price": 350},
            {"service": "Full medium SUV", "price": 375},
            {"service": "Full large SUV", "price": 400},
            {"service": "Full 4 door pickup", "price": 300},
            {"service": "Full 2 door pickup", "price": 250},
            {"service": "Full minivan", "price": 450},
            {"service": "Front 2 windows standard", "price": 140},
            {"service": "Front 2 windows coupe", "price": 160},
            {"service": "Windshield strip", "price": 60},
            {"service": "Sunroof single pane", "price": 75},
            {"service": "Sunroof panoramic/double", "price": 150},
            {"service": "Back glass only truck", "price": 125},
            {"service": "Back glass only other", "price": 150},
            {"service": "One door glass", "price": 90},
            {"service": "Tint removal per door", "price": 25},
            {"service": "Tint removal rear window", "price": 150}
        ]
        await prices_collection.insert_many(prices)
        print("Price list loaded!")

# --- 2. THE SIMULATOR WEBPAGE ---
@app.get("/", response_class=HTMLResponse)
async def simulator_ui():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Tintlife Simulator</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; display: flex; flex-direction: column; height: 90vh; }
            h1 { font-size: 20px; color: #fff; margin-bottom: 20px; text-align: center; }
            #chat-box { flex-grow: 1; border: 1px solid #333; border-radius: 8px; padding: 15px; overflow-y: scroll; background: #1e1e1e; margin-bottom: 15px; display: flex; flex-direction: column; gap: 10px; }
            .message { padding: 10px 14px; border-radius: 18px; max-width: 80%; line-height: 1.4; font-size: 15px; }
            .user { background: #0084ff; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
            .sam { background: #333; color: white; align-self: flex-start; border-bottom-left-radius: 4px; }
            .input-area { display: flex; gap: 10px; }
            input[type="text"] { flex-grow: 1; padding: 15px; border-radius: 24px; border: 1px solid #444; background: #2a2a2a; color: white; font-size: 16px; outline: none; }
            button { padding: 15px 25px; border-radius: 24px; border: none; background: #0084ff; color: white; font-size: 16px; font-weight: bold; cursor: pointer; }
            button:active { background: #0066cc; }
        </style>
    </head>
    <body>
        <h1>Tintlife Booking Agent Test</h1>
        <div id="chat-box"></div>
        <div class="input-area">
            <input type="text" id="user-input" placeholder="Type as the customer..." onkeypress="handleKeyPress(event)">
            <button onclick="sendMessage()">Send</button>
        </div>
        <script>
            let history = [];
            const chatBox = document.getElementById('chat-box');
            const userInput = document.getElementById('user-input');
            function addMessage(text, sender) {
                const div = document.createElement('div');
                div.className = 'message ' + sender;
                div.innerText = text;
                chatBox.appendChild(div);
                chatBox.scrollTop = chatBox.scrollHeight;
            }
            function handleKeyPress(e) {
                if (e.key === 'Enter') sendMessage();
            }
            async function sendMessage() {
                const text = userInput.value.trim();
                if (!text) return;
                addMessage(text, 'user');
                userInput.value = '';
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ message: text, history: history })
                });
                const data = await response.json();
                addMessage(data.reply, 'sam');
                history = data.updated_history;
            }
        </script>
    </body>
    </html>
    """
    return html_content

# --- 3. THE AGENT LOGIC ---
class ChatRequest(BaseModel):
    message: str
    history: list = []

@app.post("/chat")
async def chat(request: ChatRequest):
    prices_cursor = prices_collection.find({})
    prices_list = await prices_cursor.to_list(length=100)
    price_text = "\n".join([f"- {p['service']}: ${p['price']}" for p in prices_list])

    system_prompt = f"""You are Sam, Tintlife's booking assistant. You text the way Leigh texts — casual, direct, friendly.
Rules:
- Never claim to be Leigh. If asked, say: "It's Sam, Tintlife's booking assistant. I can get Leigh for you if you need to speak with him."
- Before quoting, ALWAYS ask for year, make, and model of the vehicle.
- All prices are PLUS HST. Always say "$X plus HST".
- Any full tint includes ONE FREE windshield strip. Mention this after quoting.
- Windshield tint is OWNER ONLY. If asked, say "Leigh handles that personally — I'll get him to reach out" and stop.
- Rear window removal: Warn them it can damage defroster lines, ask if they agree before booking.
- Dealerships: If they sound like a dealership salesperson, just say "I'll get Leigh to reach out."
- Keep replies short, casual, and text-message style.

Here is your exact price list to match vehicles against:
{price_text}
"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.history:
        messages.append(msg)
    messages.append({"role": "user", "content": request.message})

    # Call Groq (free model)
    response = await ai_client.chat.completions.create(
        model="llama-3.3-70b-versatile", # Free model on Groq
        messages=messages
    )
    
    reply = response.choices[0].message.content
    
    updated_history = request.history + [
        {"role": "user", "content": request.message},
        {"role": "assistant", "content": reply}
    ]

    return {"reply": reply, "updated_history": updated_history}
