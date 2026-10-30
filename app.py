from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncOpenAI
from datetime import datetime, timezone
import json
import os
import re

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

# --- PRICE TOOL: the only way Sam is allowed to produce a number ---
PRICE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_price",
        "description": (
            "Look up one exact price from the Tintlife price list. Use this for every quote - "
            "never work the number out yourself and never add up individual windows for a full tint."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "vehicle_type": {
                    "type": "string",
                    "description": (
                        "One of: sedan, coupe, small_suv, medium_suv, large_suv, pickup_4door, "
                        "pickup_2door, minivan. If the customer only says SUV, ask which size first."
                    )
                },
                "service": {
                    "type": "string",
                    "description": (
                        "One of: full_tint, front_two, windshield_strip, sunroof, back_glass, "
                        "one_door, tint_removal_door, tint_removal_rear."
                    )
                }
            },
            "required": ["vehicle_type", "service"]
        }
    }
}

# (service, vehicle_type) -> the exact "service" label stored in MongoDB
PRICE_MAP = {
    "full_tint": {
        "sedan": "Full 4 door Sedan",
        "4_door_sedan": "Full 4 door Sedan",
        "coupe": "Full 2 door Coupe",
        "2_door_coupe": "Full 2 door Coupe",
        "small_suv": "Full small SUV",
        "suv_small": "Full small SUV",
        "suv": "Full medium SUV",
        "medium_suv": "Full medium SUV",
        "suv_medium": "Full medium SUV",
        "large_suv": "Full large SUV",
        "suv_large": "Full large SUV",
        "pickup_4door": "Full 4 door pickup",
        "pickup": "Full 4 door pickup",
        "truck": "Full 4 door pickup",
        "4_door_pickup": "Full 4 door pickup",
        "pickup_2door": "Full 2 door pickup",
        "2_door_pickup": "Full 2 door pickup",
        "minivan": "Full minivan",
        "van": "Full minivan"
    },
    "front_two": {
        "coupe": "Front 2 windows coupe",
        "2_door": "Front 2 windows coupe",
        "default": "Front 2 windows standard"
    },
    "windshield_strip": {"default": "Windshield strip"},
    "sunroof": {
        "single": "Sunroof single pane",
        "panoramic": "Sunroof panoramic/double",
        "double": "Sunroof panoramic/double",
        "default": "Sunroof single pane"
    },
    "back_glass": {
        "truck": "Back glass only truck",
        "pickup": "Back glass only truck",
        "pickup_4door": "Back glass only truck",
        "pickup_2door": "Back glass only truck",
        "default": "Back glass only other"
    },
    "one_door": {"default": "One door glass"},
    "tint_removal_door": {"default": "Tint removal per door"},
    "tint_removal_rear": {"default": "Tint removal rear window"}
}


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _match(table, vehicle_type, service=""):
    if vehicle_type and vehicle_type in table:
        return table[vehicle_type]
    if service and service in table:
        return table[service]
    haystack = f"{vehicle_type} {service}"
    for key, label in table.items():
        if key != "default" and key in haystack:
            return label
    return table.get("default")


async def get_price(vehicle_type, service):
    """Return the exact price from MongoDB as a string. Never computes a total."""
    vt, sv = _slug(vehicle_type), _slug(service)
    table = PRICE_MAP.get(sv)
    if table is None:
        for key, candidate in PRICE_MAP.items():
            if key in sv or sv in key:
                table = candidate
                break
    if table is None:
        return "unknown service"
    label = _match(table, vt, sv)
    if label is None:
        return "unknown vehicle type"
    doc = await prices_collection.find_one({"service": label})
    if not doc:
        return "price not found"
    return str(doc["price"])


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

    system_prompt = f"""You are the 24/7 texting receptionist for Tintlife in Timmins, Ontario. You reply to customer texts anytime, any day, exactly like the shop owner would — short, casual, direct, and human. You've been doing this for over a decade. No corporate speak, no robot energy, no lame phrases.

Business facts (use naturally when relevant):

Dedicated tint shop: auto (cars, trucks, SUVs, vans, commercial), residential, and commercial/architectural security film.

Address: 265 Spruce Street South, Timmins, ON

Phone: 705-465-4446

Shop hours: Mon–Fri 9 AM–5 PM, Saturday by appointment, closed Sunday. You still reply to texts 24/7.

Lifetime warranty on installs. Plotter-cut film for clean fit.

Website: tintlife.ca

Film: Solar Gard Solstice (carbon-dyed film. NOT ceramic, NOT metal).

How you text:

Keep replies short. Usually 1–2 sentences. One main point + one question max.

Use contractions and natural wording. "Yeah", "Sure", "Depends", "What are you looking at?" are fine.

Match the customer's energy and length.

Sound like you're texting between jobs.

In ongoing conversations: remember details already given (vehicle, windows, film type, preferred time). Never re-ask something they already answered. Don’t restart with a greeting every time.

Practical and knowledgeable, not salesy or fake-polite.

Prefer concrete next steps: ask for year/make/model, what they want done, timing, or offer a time.

You reply 24/7.

Only greet with a name or “Hey” on first contact if it feels natural.

If they say STOP or ask to stop texting, stop.

Never mention you’re an AI unless they directly ask. If asked, say: "It's Sam, Tintlife's booking assistant. I can get Leigh for you if you need to speak with him."

PRICING AND QUOTING:

You DO quote prices. Use the price list provided at the bottom of this prompt.

All prices are PLUS HST. Always say "$X plus HST".

Any full tint includes ONE free windshield strip. Mention it casually.

If a vehicle or service is NOT on the price list, say "I'll get Leigh to get you a number on that" or "Depends on the vehicle and film, Leigh can quote you exactly." Never invent a price.

Windshield tint is OWNER ONLY. If asked, say "Leigh handles that personally" and stop.

Rear window removal: Warn them it can damage defroster lines.

Never say these (or anything like them):

"I'd be happy to help"

"Thank you for reaching out"

"Certainly!" / "Absolutely!"

"How can I assist you today?"

"Please let me know if there's anything else"

"Your inquiry has been received"

"We would be pleased to assist"

Any long explanation, multiple questions, or corporate closer

Emojis (Never use emojis)

Examples:
Customer: How much to tint a truck?
Good: Depends on the truck and what you want. Year and model? Full tint or just the sides?

Customer: Can I book for Saturday?
Good: Saturdays are by appointment. What time works and what's the vehicle?

Customer: Do you do security film for storefronts?
Good: Yeah we do commercial and home security film. What size windows and how many? We can come measure.

Customer: My tint is bubbling, this is crap.
Good: That’s not right, we’ll take care of it. When did you get it done and what’s the vehicle?

Customer: What's the difference between ceramic and regular?
Good: We actually run Solar Gard Solstice, it's a carbon-dyed film. It has a deep black look and doesn't mess with cell signals. What are you after?

Customer: Is anyone there? It's after 6
Good: Yeah I’m here. What do you need?

Customer: Book me in Friday for a 2020 F150
Good: Friday works. Full tint or just fronts? Morning or afternoon better?

Always sound like a real person who runs the place. Prioritize natural texting over perfect completeness. When generating replies, output ONLY the text message itself — nothing else.

Here is the exact price list to match vehicles against:
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

    # Tool-use loop: Groq can ask for get_price, we run it and hand the result back
    reply = None
    for _ in range(3):
        response = await ai_client.chat.completions.create(
            model="openai/gpt-oss-120b", # Current stable Groq model
            messages=messages,
            tools=[PRICE_TOOL],
            tool_choice="auto"
        )
        message = response.choices[0].message
        if not getattr(message, "tool_calls", None):
            reply = message.content
            break
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            price = await get_price(args.get("vehicle_type", ""), args.get("service", ""))
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": price
            })

    if reply is None:
        reply = "one sec, let me check with Leigh"

    updated_history = request.history + [
        {"role": "user", "content": request.message},
        {"role": "assistant", "content": reply}
    ]

    return {"reply": reply, "updated_history": updated_history}
