from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncOpenAI
from datetime import datetime, timezone
import os

app = FastAPI()

# Connect to Database
mongo_url = os.environ.get("MONGO_URI")
client = AsyncIOMotorClient(mongo_url)
db = client.tintlife
prices_collection = db.prices

# Rules the owner teaches via *change, - kept out of the price data on purpose
rules_collection = db.custom_rules

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
            .status { display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 13px; letter-spacing: 0.3px; color: #b0b0b0; margin: -12px 0 14px; }
            .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #34c759; box-shadow: 0 0 8px rgba(52, 199, 89, 0.55); transition: background 0.2s ease, box-shadow 0.2s ease; }
            .status.typing .status-dot { background: #ffd60a; box-shadow: 0 0 8px rgba(255, 214, 10, 0.55); animation: status-pulse 1s ease-in-out infinite; }
            .status.error .status-dot { background: #ff453a; box-shadow: 0 0 8px rgba(255, 69, 58, 0.55); }
            @keyframes status-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
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
        <div id="status" class="status online" role="status" aria-live="polite">
            <span class="status-dot"></span>
            <span id="status-text">Online</span>
        </div>
        <div id="chat-box"></div>
        <div class="input-area">
            <input type="text" id="user-input" placeholder="Type as the customer..." onkeypress="handleKeyPress(event)">
            <button onclick="sendMessage()">Send</button>
        </div>
        <script>
            let history = [];
            const chatBox = document.getElementById('chat-box');
            const userInput = document.getElementById('user-input');
            const statusEl = document.getElementById('status');
            const statusText = document.getElementById('status-text');
            function setStatus(state, text) {
                statusEl.className = 'status ' + state;
                statusText.textContent = text;
            }
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
                setStatus('typing', 'Sam is typing...');
                try {
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ message: text, history: history })
                    });
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    const data = await response.json();
                    addMessage(data.reply, 'sam');
                    history = data.updated_history;
                    setStatus('online', 'Online');
                } catch (error) {
                    console.error('Chat request failed:', error);
                    addMessage("Sorry - I couldn't reach the booking agent. Please try again.", 'sam');
                    setStatus('error', 'Error');
                }
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
    text = request.message.strip()
    lowered = text.lower()

    # *change, <rule> - saved to custom_rules, never forwarded to the model
    if lowered.startswith("*change,"):
        new_rule = text[len("*change,"):].strip()
        if not new_rule:
            return {"reply": "What's the rule?", "updated_history": request.history}
        await rules_collection.insert_one({
            "rule": new_rule,
            "created_at": datetime.now(timezone.utc)
        })
        return {"reply": "Got it. Rule added.", "updated_history": request.history}

    # *clear - wipes every custom rule
    if lowered == "*clear":
        await rules_collection.delete_many({})
        return {"reply": "Rules cleared.", "updated_history": request.history}

    prices_cursor = prices_collection.find({})
    prices_list = await prices_cursor.to_list(length=100)
    price_text = "\n".join([f"- {p['service']}: ${p['price']}" for p in prices_list])

    system_prompt = f"""PERSONA:
You are Sam, Leigh's booking assistant at Tintlife. You are charismatic, laid-back, and friendly. You text like a real guy in his 30s who works at a tint shop. You have a sense of humor and actually care about the customer's car.

VARY YOUR PHRASING:
Never repeat the exact same greeting or sentence structure twice in a row. You have a wide vocabulary. If you greeted someone with "hey whats up", use "yup what do you need" or "yo" next time. You are a human having a real conversation, not a machine reading a script. Shake up how you ask for things so it always feels fresh.

EMOTION & CHARISMA:
React to what the customer says. If they have a nice car, say "oh nice" or "those are sick". If they are frustrated, say "ah that sucks man". Mirror their energy. NEVER sound like a customer service bot. Do not use phrases like "I can help with that" or "please provide".

GATHERING INFO:
You need the year, make, model, and body style to quote. But DO NOT list this like a form. Ask naturally. If they say "I need a tint", say "cool, what are you driving?" Once they tell you the car, ask for the year if they didn't include it.

EXAMPLES OF HOW YOU TALK:
- Customer: "hey" -> Sam: "hey whats up man"
- Customer: "need tint" -> Sam: "yeah no prob, what kind of vehicle you got?"
- Customer: "2020 civic" -> Sam: "nice, sedan? full tint is 350 plus hst"
- Customer: "I have a 2021 f150" -> Sam: "love those trucks. full tint on a 4 door pickup is 300 plus hst, comes with a free windshield strip"

HARD BUSINESS RULES:
- Never claim to be Leigh. If asked, say: "It's Sam, Tintlife's booking assistant. I can get Leigh for you if you need to speak with him."
- All prices are PLUS HST.
- Any full tint includes ONE free windshield strip. Mention it casually.
- Windshield tint is OWNER ONLY. If asked, say "Leigh handles that personally" and stop.
- Rear window removal: Warn them it can damage defroster lines.
- Dealerships: If they sound like a dealership, say "I'll get Leigh to reach out."
- No emojis. Keep replies short.
- Never bring up scheduling, times or booking until the customer has actually asked for a service or a price.
- PRICING LOGIC: A "Full Tint" ALREADY INCLUDES all doors, quarter glasses, and the rear glass. If a customer asks for a full tint and then says "just the doors and back glass", they are confirming what a full tint is. NEVER break down a full tint into individual door or back glass prices. ALWAYS use the flat Full Tint price for that vehicle type. Only use the "One door glass" or "Back glass only" prices if the customer explicitly says they ONLY want one window done, and are NOT getting the rest of the car tinted.
- NEVER show your math or use bullet points when quoting. Just give the final price in one short, casual sentence.

PRICE LIST - match the vehicle to the closest line:
{price_text}
"""

    custom_rules = await rules_collection.find({}).sort([("created_at", 1), ("_id", 1)]).to_list(length=200)
    if custom_rules:
        rules_block = "\n".join(f"- {doc['rule']}" for doc in custom_rules)
        system_prompt += (
            "\n\nCRITICAL NEW RULES:\n"
            "The owner added these live. They override anything above that conflicts with them.\n"
            f"{rules_block}"
        )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.history:
        messages.append(msg)
    messages.append({"role": "user", "content": request.message})

    # Call Groq (free model)
    response = await ai_client.chat.completions.create(
        model="openai/gpt-oss-120b", # Current stable Groq model
        messages=messages
    )
    
    reply = response.choices[0].message.content
    
    updated_history = request.history + [
        {"role": "user", "content": request.message},
        {"role": "assistant", "content": reply}
    ]

    return {"reply": reply, "updated_history": updated_history}
