import streamlit as st
import requests
import json
from datetime import datetime, timedelta
import time

# ========== API FUNCTIONS ==========
apify_api_key = st.secrets.get("APIFY", "")
groq_api_key = st.secrets.get("GROQ", "")

def extract_username_from_url(profile_url: str) -> str:
    """Extract username from LinkedIn URL."""
    if "/in/" in profile_url:
        return profile_url.split("/in/")[-1].strip("/").split("?")[0]
    return profile_url

def start_apify_run(username: str, api_key: str) -> dict:
    """
    Start the Apify actor run asynchronously.
    HTTP 201 status means SUCCESS - run created.
    """
    try:
        endpoint = "https://api.apify.com/v2/acts/apimaestro~linkedin-profile-detail/runs"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {"username": username, "includeEmail": False}
        
        response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 201:
            run_data = response.json()
            return {
                "run_id": run_data["data"]["id"],
                "dataset_id": run_data["data"]["defaultDatasetId"],
                "status": "RUNNING"
            }
        else:
            st.error(f"Failed to start actor. Status: {response.status_code}")
            return None
            
    except Exception as e:
        st.error(f"Error starting Apify run: {str(e)}")
        return None

def scrape_linkedin_posts(profile_url: str, api_key: str) -> list:
    """
    Scrape last 2 posts from a LinkedIn profile using Apify actor.
    Filter for last 30 days only.
    """
    try:
        endpoint = (
            "https://api.apify.com/v2/acts/"
            "apimaestro~linkedin-batch-profile-posts-scraper/"
            "run-sync-get-dataset-items?token=" + api_key
        )

        payload = {
            "includeEmail": False,
            "usernames": [profile_url.strip()]  # MUST be a list
        }

        headers = {"Content-Type": "application/json"}

        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=90
        )

        if response.status_code not in (200,201):
            st.error(
                f"Failed. Status: {response.status_code}, "
                f"Response: {response.text[:500]}"
            )
            return []

        data = response.json()

        if not isinstance(data, list):
            st.warning("Unexpected response structure from Apify.")
            return []

        # Filter posts from last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        filtered_posts = []
        
        for post in data:
            if not isinstance(post, dict):
                continue
                
            # Check timestamp
            timestamp = post.get('timestamp')
            if timestamp:
                try:
                    post_date = datetime.fromtimestamp(timestamp / 1000)  # Convert ms to seconds
                    if post_date >= thirty_days_ago:
                        filtered_posts.append(post)
                except:
                    # If timestamp parsing fails, skip
                    continue
        
        # Return only last 2 posts from last 30 days
        return filtered_posts[:2]

    except Exception as e:
        st.error(f"Error scraping posts: {str(e)}")
        return []

def filter_professional_posts(posts):
    """
    Filter posts: keep only professional content, remove hiring/festive posts.
    """
    if not posts:
        return []

    filtered_posts = []
    exclude_keywords = ['hiring', 'job', 'diwali', 'holiday', 'festival', 'birthday', 
                       'anniversary', 'wish', 'congrat', 'thank', 'happy']
    
    for post in posts:
        if not isinstance(post, dict):
            continue
            
        post_text = post.get('text', '').lower()
        
        # Check if it contains junk keywords
        has_excluded = any(keyword in post_text for keyword in exclude_keywords)
        
        # Check if it's professional content
        professional_keywords = ['project', 'launch', 'achievement', 'team', 'lead', 
                                'develop', 'build', 'create', 'innovation', 'growth',
                                'strategy', 'business', 'industry', 'market', 'tech',
                                'software', 'product', 'service', 'client', 'customer']
        
        has_professional = any(keyword in post_text for keyword in professional_keywords)
        
        # Keep if it's professional AND not excluded
        if has_professional and not has_excluded:
            filtered_posts.append(post)
    
    return filtered_posts[:2]

def poll_apify_run_with_status(run_id: str, dataset_id: str, api_key: str) -> dict:
    """
    Poll the Apify run with proper status updates.
    Returns profile data when successful.
    """
    max_attempts = 60
    headers = {"Authorization": f"Bearer {api_key}"}
    
    with st.spinner(""):
        progress_bar = st.progress(0)
        
        for attempt in range(max_attempts):
            progress = min(100, int((attempt + 1) / max_attempts * 80))
            progress_bar.progress(progress)
            
            try:
                status_endpoint = f"https://api.apify.com/v2/actor-runs/{run_id}"
                status_response = requests.get(status_endpoint, headers=headers, timeout=15)
                
                if status_response.status_code == 200:
                    status_data = status_response.json()["data"]
                    current_status = status_data.get("status", "UNKNOWN")
                    
                    if current_status == "SUCCEEDED":
                        progress_bar.progress(95)
                        
                        dataset_endpoint = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
                        dataset_response = requests.get(dataset_endpoint, headers=headers, timeout=30)
                        
                        if dataset_response.status_code == 200:
                            items = dataset_response.json()
                            progress_bar.progress(100)
                            if isinstance(items, list) and len(items) > 0:
                                return items[0]
                            elif isinstance(items, dict):
                                return items
                        else:
                            st.error(f"Failed to fetch dataset: {dataset_response.status_code}")
                            return None
                            
                    elif current_status in ["FAILED", "TIMED-OUT", "ABORTED"]:
                        st.error(f"Apify run failed: {current_status}")
                        return None
                        
                    elif current_status == "RUNNING":
                        time.sleep(10)
                        continue
                        
                else:
                    time.sleep(10)
                    
            except Exception as e:
                time.sleep(10)
    
    st.error("Polling timeout - Apify taking too long")
    return None

def generate_research_brief(profile_data: dict, api_key: str) -> str:
    """
    Generate research brief with improved reliability.
    """
    try:
        profile_summary = json.dumps(profile_data, indent=2)[:2000]
        
        prompt = f'''
        Create a concise research brief for sales prospecting.
        
        PROFILE DATA:
        {profile_summary}
        
        Create a brief with these sections:
        1. KEY PROFILE INSIGHTS
        2. CAREER PATTERNS & CURRENT FOCUS
        3. BUSINESS CONTEXT & POTENTIAL NEEDS
        4. PERSONALIZATION OPPORTUNITIES
        
        Keep it factual and actionable.
        '''
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a research analyst creating factual briefs."
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1200
        }
        
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                return f"Research brief generation encountered an issue (Status: {response.status_code}). The profile data is loaded and ready for message generation."
                
        except requests.exceptions.Timeout:
            return "Research brief generation is taking longer than expected. Profile data is loaded and ready for message generation."
        except Exception as e:
            return f"Research brief service temporarily unavailable. Profile data loaded successfully."
            
    except Exception as e:
        return f"Profile analysis ready. Focus on message generation."

def analyze_and_generate_message(prospect_data: dict, sender_info: dict, api_key: str, 
                                user_instructions: str = None, previous_message: str = None) -> list:
    """
    Generate LinkedIn messages with CONCISE role depth (20 words max) and sender's info in second line.
    Returns list of 3 complete message options (250-300 characters).
    """
    try:
        # 1. EXTRACT PROSPECT DATA CONCISELY
        prospect_name = "there"
        prospect_company = ""
        prospect_role = ""
        
        if isinstance(prospect_data, dict):
            # Extract name (first name only)
            if prospect_data.get('fullname'):
                name_parts = prospect_data['fullname'].split()
                prospect_name = name_parts[0] if name_parts else "there"
            elif prospect_data.get('basic_info') and prospect_data['basic_info'].get('fullname'):
                name_parts = prospect_data['basic_info']['fullname'].split()
                prospect_name = name_parts[0] if name_parts else "there"
            
            # Extract current position (simplified)
            if prospect_data.get('headline'):
                headline = prospect_data['headline']
                # Keep it simple: just get role
                if ' at ' in headline:
                    prospect_role = headline.split(' at ')[0].strip()
                elif ' - ' in headline:
                    prospect_role = headline.split(' - ')[0].strip()
            
            # Fallback to experience
            if not prospect_role and prospect_data.get('experience'):
                experiences = prospect_data.get('experience', [])
                if experiences and len(experiences) > 0:
                    prospect_role = experiences[0].get('title', '')
        
        # 2. EXTRACT RECENT POST (CONCISE)
        recent_post_topic = ""
        if isinstance(prospect_data, dict):
            posts = prospect_data.get('posts', [])
            if posts and len(posts) > 0 and isinstance(posts[0], dict):
                post_text = posts[0].get('text', '')
                if post_text:
                    # Take first 50 characters max
                    recent_post_topic = post_text[:50].replace('\n', ' ').strip()
        
        # 3. EXTRACT SENDER INFO
        sender_name = sender_info.get('name', 'Professional')
        sender_first_name = sender_name.split()[0] if sender_name else "Professional"
        sender_role_desc = sender_info.get('role_desc', '')
        
        # 4. CONCISE PROMPT FOR SHORT MESSAGES
        system_prompt = f'''You are an expert LinkedIn message writer. Generate 3 different connection requests.

CRITICAL RULES:
1. Each message MUST be 250-300 characters TOTAL
2. Keep role explanation to 20 words MAX in the hook
3. Structure: Hi [Name], [concise hook], [connection request]
4. INCLUDE in EVERY message: "As someone who {sender_role_desc},"
5. Be direct, no lengthy explanations
6. If mentioning a post, keep it brief (1 sentence)
7. Role depth means: Show you understand their work, but don't over-explain

EXAMPLE OF GOOD STRUCTURE (under 300 chars):
"Hi Sarah, Your approach to product strategy shows clear customer focus. As someone who helps tech teams scale products, I'd appreciate connecting to exchange quick thoughts."

BAD (too long):
"Hi Sarah, Crafting customer-centric banking experiences through tailored product offerings seems like a fascinating challenge. As someone who helps banks..."

PROSPECT INFO:
Name: {prospect_name}
Role: {prospect_role or 'Professional'}
Recent Post: {recent_post_topic or 'No recent post mentioned'}

YOUR CONTEXT:
Name: {sender_first_name}
About You: {sender_role_desc}

Generate 3 different 250-300 character messages. Each must be concise and follow the structure.'''

        # 5. USER PROMPT
        if user_instructions and previous_message:
            user_prompt = f'''Make this message shorter and more concise: {previous_message[:150]}

Instructions: {user_instructions}

Generate 3 shorter versions (250-300 chars each).'''
        else:
            user_prompt = '''Generate 3 concise connection messages following all rules above.'''
        
        # 6. API CALL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 800,  # Reduced for shorter messages
            "stream": False
        }
        
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            
            # Parse and format messages
            messages = []
            lines = content.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if line.startswith('Option') or line.startswith('Message') or line.startswith('Version'):
                    continue
                if line and len(line) > 50 and line[0].isalpha():  # Looks like message text
                    # Format it
                    if not line.startswith(f"Hi {prospect_name}"):
                        line = f"Hi {prospect_name},\n{line}"
                    if not line.strip().endswith(f"Best,\n{sender_first_name}"):
                        line = f"{line}\nBest,\n{sender_first_name}"
                    
                    # Truncate if too long (shouldn't be with our prompt)
                    if len(line) > 350:
                        line = line[:340] + "\nBest,\n" + sender_first_name
                    
                    messages.append(line)
            
            # Ensure we have exactly 3 messages
            if len(messages) >= 3:
                return messages[:3]
            elif messages:
                # Create variations if needed
                return messages + generate_concise_fallback(prospect_name, sender_first_name, sender_role_desc, prospect_role)[:3-len(messages)]
            else:
                # Fallback
                return generate_concise_fallback(prospect_name, sender_first_name, sender_role_desc, prospect_role)
        
        # Fallback messages
        return generate_concise_fallback(prospect_name, sender_first_name, sender_role_desc, prospect_role)
        
    except Exception as e:
        return generate_concise_fallback("there", "Professional", sender_info.get('role_desc', ''), "their role")

def generate_concise_fallback(prospect_name: str, sender_first_name: str, 
                            sender_role_desc: str, prospect_role: str) -> list:
    """Generate concise fallback messages (250-300 chars each)."""
    
    # Template messages within character limit
    templates = [
        f"Hi {prospect_name},\nYour work in {prospect_role or 'your field'} shows strong customer focus. As someone who {sender_role_desc or 'works in a related area'}, I'd appreciate connecting to exchange quick thoughts.\nBest,\n{sender_first_name}",
        
        f"Hi {prospect_name},\nYour approach to {prospect_role or 'professional work'} aligns with current industry shifts. As someone who {sender_role_desc or 'focuses on similar challenges'}, connecting would be valuable for sharing perspectives.\nBest,\n{sender_first_name}",
        
        f"Hi {prospect_name},\nThe strategy behind your {prospect_role or 'role'} shows clear direction. As someone who {sender_role_desc or 'helps in this space'}, I'd like to connect and exchange brief notes.\nBest,\n{sender_first_name}"
    ]
    
    # Ensure each is under 300 chars
    final_messages = []
    for msg in templates:
        if len(msg) > 300:
            # Truncate carefully
            lines = msg.split('\n')
            if len(lines) >= 3:
                # Keep first two lines, truncate third
                truncated = f"{lines[0]}\n{lines[1]}\n{lines[2][:100]}..."
                if len(truncated) > 300:
                    truncated = truncated[:290] + "\nBest,\n" + sender_first_name
                final_messages.append(truncated)
            else:
                final_messages.append(msg[:300])
        else:
            final_messages.append(msg)
    
    return final_messages[:3]
                                
def generate_fallback_messages(prospect_name: str, sender_first_name: str, 
                             sender_role_desc: str, prospect_role: str) -> list:
    """Generate fallback messages with role depth."""
    base_messages = [
        f"""Hi {prospect_name},
Your work in {prospect_role or 'your field'} demonstrates a commitment to professional excellence. As someone who {sender_role_desc or 'works in a related field'}, I appreciate the strategic approach you've taken. Would be great to exchange perspectives on industry developments.

Best,
{sender_first_name}""",
        
        f"""Hi {prospect_name},
Your role at as {prospect_role or 'a professional'} shows depth in navigating complex challenges. As someone who {sender_role_desc or 'focuses on similar business improvements'}, I've followed your approach with interest. Let's connect and share insights on mutual growth opportunities.

Best,
{sender_first_name}""",
        
        f"""Hi {prospect_name},
The strategic thinking evident in your {prospect_role or 'professional'} work aligns with evolving business needs. As someone who {sender_role_desc or 'works on similar transformations'}, I believe we could have valuable conversations about future directions. Would appreciate connecting to exchange notes.

Best,
{sender_first_name}"""
    ]
    
    return base_messages

# ========== STREAMLIT APPLICATION ==========

st.set_page_config(
    page_title="Linzy | AI Prospect Intelligence",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Modern CSS ---
modern_css = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #0a192f 0%, #1a1a2e 50%, #16213e 100%);
        font-family: 'Space Grotesk', sans-serif;
        min-height: 100vh;
    }
    
    .main-container {
        background: linear-gradient(145deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.02));
        backdrop-filter: blur(20px);
        border-radius: 32px;
        padding: 40px;
        margin: 20px;
        border: 1px solid rgba(0, 180, 216, 0.1);
        box-shadow: 0 50px 100px rgba(0, 180, 216, 0.1),
            inset 0 1px 0 rgba(255, 255, 255, 0.1),
            0 0 100px rgba(0, 180, 216, 0.05);
        animation: float3d 6s ease-in-out infinite;
        position: relative;
        overflow: hidden;
    }
    
    @keyframes float3d {
        0%, 100% { transform: translateY(0) rotateX(1deg); }
        50% { transform: translateY(-10px) rotateX(1deg); }
    }
    
    .gradient-text-primary {
        background: linear-gradient(135deg, #00b4d8 0%, #00ffd0 50%, #0077b6 100%);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        background-size: 200% auto;
        animation: textShimmer 3s ease-in-out infinite alternate;
    }
    
    @keyframes textShimmer {
        0% { background-position: 0% 50%; }
        100% { background-position: 100% 50%; }
    }
    
    .input-3d {
        background: rgba(255, 255, 255, 0.03);
        border: 2px solid rgba(0, 180, 216, 0.2);
        border-radius: 16px;
        padding: 18px 24px;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1rem;
        color: #e6f7ff;
        transition: all 0.3s ease;
        backdrop-filter: blur(10px);
        box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.1),
            0 4px 20px rgba(0, 180, 216, 0.1);
    }
    
    .input-3d:focus {
        background: rgba(255, 255, 255, 0.05);
        border-color: #00b4d8;
        box-shadow: 0 0 0 4px rgba(0, 180, 216, 0.15),
            inset 0 2px 8px rgba(0, 180, 216, 0.1);
        outline: none;
    }
    
    .card-3d {
        background: rgba(255, 255, 255, 0.03);
        border-radius: 24px;
        padding: 25px;
        margin: 15px 0;
        border: 1px solid rgba(0, 180, 216, 0.1);
        transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        backdrop-filter: blur(10px);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2),
            inset 0 1px 0 rgba(255, 255, 255, 0.1);
    }
    
    .card-3d:hover {
        transform: translateY(-5px);
        border-color: rgba(0, 180, 216, 0.3);
        box-shadow: 0 30px 80px rgba(0, 180, 216, 0.15),
            inset 0 1px 0 rgba(255, 255, 255, 0.15);
    }
    
    .status-orb {
        display: inline-block;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        margin-right: 12px;
        background: #ff6b6b;
        box-shadow: 0 0 20px #ff6b6b;
        animation: pulse 2s infinite;
    }
    
    .status-orb.active {
        background: #00ffd0;
        box-shadow: 0 0 20px #00ffd0;
    }
    
    @keyframes pulse {
        0%, 100% { 
            opacity: 1;
            box-shadow: 0 0 20px currentColor;
        }
        50% { 
            opacity: 0.7;
            box-shadow: 0 0 40px currentColor;
        }
    }
    
    .message-structure {
        background: linear-gradient(135deg, rgba(0, 180, 216, 0.05), rgba(0, 255, 208, 0.05));
        border-left: 4px solid #00b4d8;
        padding: 25px;
        border-radius: 20px;
        margin: 20px 0;
        font-family: 'Inter', sans-serif;
        line-height: 1.8;
        color: #e6f7ff;
        animation: slideIn 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }
    
    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #00b4d8 0%, #0077b6 100%);
        color: white;
        border: none;
        padding: 14px 28px;
        border-radius: 14px;
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        font-size: 0.95rem;
        cursor: pointer;
        transition: all 0.3s ease;
        box-shadow: 0 8px 25px rgba(0, 180, 216, 0.3),
            inset 0 1px 0 rgba(255, 255, 255, 0.2);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 12px 35px rgba(0, 180, 216, 0.4),
            inset 0 1px 0 rgba(255, 255, 255, 0.3);
    }
    
    .stButton > button:active {
        transform: translateY(0);
        box-shadow: 0 5px 20px rgba(0, 180, 216, 0.3),
            inset 0 1px 0 rgba(255, 255, 255, 0.1);
    }
    
    ::-webkit-scrollbar {
        width: 10px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #00b4d8, #0077b6);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #00ffd0, #00b4d8);
    }
</style>

<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
"""

st.markdown(modern_css, unsafe_allow_html=True)

# --- Initialize Session State ---
if 'profile_data' not in st.session_state:
    st.session_state.profile_data = None
if 'research_brief' not in st.session_state:
    st.session_state.research_brief = None
if 'generated_messages' not in st.session_state:
    st.session_state.generated_messages = []
if 'current_message_index' not in st.session_state:
    st.session_state.current_message_index = -1
if 'processing_status' not in st.session_state:
    st.session_state.processing_status = "Ready"
if 'sender_info' not in st.session_state:
    st.session_state.sender_info = {}
if 'sender_data' not in st.session_state:
    st.session_state.sender_data = None
if 'message_instructions' not in st.session_state:
    st.session_state.message_instructions = ""
if 'regenerate_mode' not in st.session_state:
    st.session_state.regenerate_mode = False

# --- Main Container ---
st.markdown('<div class="main-container">', unsafe_allow_html=True)

# --- Header Section ---
col1, col2 = st.columns([4, 1])
with col1:
    st.markdown('<h1 class="gradient-text-primary" style="font-size: 3.5rem; margin-bottom: 10px;">LINZY</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color: #8892b0; font-size: 1.2rem; margin-bottom: 40px;">AI Powered LinkedIn Message Generator</p>', unsafe_allow_html=True)
with col2:
    sender_name = st.session_state.sender_info.get('name', 'Not Set')
    sender_display = sender_name.split()[0][:15] if sender_name else "Not Set"
    
    st.markdown(f'''
    <div class="card-3d" style="text-align: center; padding: 20px;">
        <div style="display: flex; align-items: center; justify-content: center; margin-bottom: 10px;">
            <span class="status-orb {'active' if st.session_state.profile_data else ''}"></span>
            <span style="color: #e6f7ff; font-weight: 600;">{st.session_state.processing_status}</span>
        </div>
        <div style="color: #8892b0; font-size: 0.9rem;">
            <div>Sender: {sender_display}</div>
            <div>Messages: {len(st.session_state.generated_messages)}</div>
            <div>{datetime.now().strftime("%H:%M:%S")}</div>
        </div>
    </div>
    ''', unsafe_allow_html=True)

# --- Sender Information Section (DIRECT INPUT) ---
st.markdown("---")
st.markdown('<h3 style="color: #e6f7ff; margin-bottom: 25px;">Your Information</h3>', unsafe_allow_html=True)

col_s1, col_s2 = st.columns([1, 1])

with col_s1:
    sender_name_input = st.text_input(
        "Your Name (for signature)",
        value=st.session_state.sender_info.get('name', ''),
        placeholder="e.g., John",
        key="sender_name_input"
    )
    
    sender_role_desc = st.text_area(
        "What You Do (for 2nd line of message)",
        value=st.session_state.sender_info.get('role_desc', ''),
        placeholder="Example: works on AI-driven sales solutions, focuses on B2B SaaS growth, builds customer engagement platforms",
        height=100,
        key="sender_role_desc",
        help="This will be used in the second line: 'As someone who [your text here],'"
    )

with col_s2:
    sender_current_role = st.text_input(
        "Your Current Role",
        value=st.session_state.sender_info.get('current_role', ''),
        placeholder="e.g., Senior Product Manager",
        key="sender_current_role"
    )
    
    sender_company = st.text_input(
        "Your Company",
        value=st.session_state.sender_info.get('company', ''),
        placeholder="e.g., TechCorp Inc.",
        key="sender_company"
    )

col_save, col_clear = st.columns([1, 1])
with col_save:
    if st.button("Save Your Information", use_container_width=True):
        if sender_name_input and sender_role_desc:
            st.session_state.sender_info = {
                'name': sender_name_input,
                'role_desc': sender_role_desc,
                'current_role': sender_current_role,
                'company': sender_company
            }
            st.success("Information saved! Now analyze a prospect.")
            st.rerun()
        else:
            st.warning("Please enter at least your Name and What You Do")

with col_clear:
    if st.button("Clear Information", use_container_width=True):
        st.session_state.sender_info = {}
        st.rerun()

# Display saved sender info
if st.session_state.sender_info:
    with st.expander("Your Saved Information", expanded=False):
        info = st.session_state.sender_info
        st.markdown(f"""
        <div class="card-3d">
            <div style="color: #e6f7ff;">
                <div style="margin-bottom: 10px;"><strong>Name:</strong> {info.get('name', 'N/A')}</div>
                <div style="margin-bottom: 10px;"><strong>Role:</strong> {info.get('current_role', 'N/A')}</div>
                <div style="margin-bottom: 10px;"><strong>Company:</strong> {info.get('company', 'N/A')}</div>
                <div><strong>About You:</strong> {info.get('role_desc', 'N/A')}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# --- Prospect Analysis Section ---
st.markdown("---")
st.markdown('<h3 style="color: #e6f7ff; margin-bottom: 20px;">Prospect Analysis</h3>', unsafe_allow_html=True)

prospect_col1, prospect_col2 = st.columns([3, 1])

with prospect_col1:
    prospect_linkedin_url = st.text_input(
        "Prospect LinkedIn Profile URL",
        placeholder="https://linkedin.com/in/prospectprofile",
        key="prospect_url"
    )

with prospect_col2:
    st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
    analyze_prospect_clicked = st.button(
        "Analyze Prospect",
        use_container_width=True,
        key="analyze_prospect",
        disabled=not st.session_state.sender_info or not prospect_linkedin_url
    )

if not st.session_state.sender_info:
    st.warning("Please set up your information first to generate personalized messages.")

# Handle prospect analysis
if analyze_prospect_clicked and prospect_linkedin_url and st.session_state.sender_info:
    if not apify_api_key or not groq_api_key:
        st.error("API configuration required.")
    else:
        st.session_state.processing_status = "Analyzing Prospect"
        
        username = extract_username_from_url(prospect_linkedin_url)
        run_info = start_apify_run(username, apify_api_key)
        
        if run_info:
            # 1. Get main profile data
            profile_data = poll_apify_run_with_status(
                run_info["run_id"],
                run_info["dataset_id"],
                apify_api_key
            )
            
            if profile_data:
                # 2. Scrape recent posts (last 30 days only)
                st.session_state.processing_status = "Scraping Recent Posts (30 days)"
                raw_posts = scrape_linkedin_posts(prospect_linkedin_url, apify_api_key)
                
                # 3. Filter for professional content only
                relevant_posts = filter_professional_posts(raw_posts)
                
                # Add filtered posts to profile data
                profile_data['posts'] = relevant_posts
                
                # 4. Generate research brief
                st.session_state.profile_data = profile_data
                st.session_state.processing_status = "Generating Research"
                
                research_brief = generate_research_brief(profile_data, groq_api_key)
                st.session_state.research_brief = research_brief
                st.session_state.processing_status = "Ready"
                
                st.success("Prospect analysis complete!")
                st.session_state.generated_messages = []
                st.session_state.current_message_index = -1
            else:
                st.session_state.processing_status = "Error"
                st.error("Failed to analyze prospect profile.")

# --- Results Display ---
if st.session_state.profile_data and st.session_state.research_brief and st.session_state.sender_info:
    st.markdown("---")
    
    tab1, tab2, tab3 = st.tabs([
        "Message Generation", 
        "Research Brief", 
        "Profile Data"
    ])
    
    with tab1:
        st.markdown('<h3 style="color: #e6f7ff; margin-bottom: 25px;">Generate Message</h3>', unsafe_allow_html=True)
        
        col_gen1, col_gen2 = st.columns([2, 1])
        
        with col_gen1:
            if st.button("Generate AI Messages", use_container_width=True, key="generate_message"):
                with st.spinner("Creating personalized messages with role depth..."):
                    messages = analyze_and_generate_message(
                        st.session_state.profile_data,
                        st.session_state.sender_info,
                        groq_api_key
                    )
                    
                    if messages:
                        st.session_state.generated_messages = []
                        for i, msg in enumerate(messages):
                            st.session_state.generated_messages.append({
                                "text": msg,
                                "char_count": len(msg),
                                "option": i + 1
                            })
                        st.session_state.current_message_index = 0
                        st.rerun()
            
        with col_gen2:
            if len(st.session_state.generated_messages) > 0:
                if st.button(
                    "Refine Message", 
                    use_container_width=True,
                    key="refine_message"
                ):
                    st.session_state.regenerate_mode = True
                    st.rerun()
        
        # Display current message
        if len(st.session_state.generated_messages) > 0:
            current_msg_data = st.session_state.generated_messages[st.session_state.current_message_index]
            current_msg = current_msg_data["text"]
            char_count = current_msg_data["char_count"]
            
            st.markdown(f'''
            <div class="message-structure">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 20px;">
                    <div>
                        <h4 style="color: #e6f7ff; margin: 0;">Option {current_msg_data['option']}</h4>
                        <p style="color: #8892b0; font-size: 0.9rem; margin: 5px 0 0 0;">
                            {char_count} characters
                        </p>
                    </div>
                    <div style="background: linear-gradient(135deg, rgba(0, 180, 216, 0.1), rgba(0, 255, 208, 0.1)); padding: 8px 16px; border-radius: 12px;">
                        <span style="color: #00ffd0; font-weight: 600;">{char_count}/300 characters</span>
                    </div>
                </div>
                <div style="background: rgba(255, 255, 255, 0.03); padding: 25px; border-radius: 16px; border: 1px solid rgba(0, 180, 216, 0.1); margin: 20px 0;">
                    <pre style="white-space: pre-wrap; font-family: 'Inter', sans-serif; line-height: 1.8; margin: 0; color: #e6f7ff; font-size: 1.05rem; word-wrap: break-word; overflow-wrap: break-word;">
{current_msg}
                    </pre>
                </div>
            </div>
            ''', unsafe_allow_html=True)
            
            col_copy, col_prev, col_next, col_count = st.columns([2, 1, 1, 1])
            
            with col_copy:
                st.code(current_msg, language=None)
            
            with col_prev:
                if st.button("Previous", use_container_width=True, disabled=st.session_state.current_message_index <= 0):
                    st.session_state.current_message_index -= 1
                    st.session_state.regenerate_mode = False
                    st.rerun()
            
            with col_next:
                if st.button("Next", use_container_width=True, disabled=st.session_state.current_message_index >= len(st.session_state.generated_messages) - 1):
                    st.session_state.current_message_index += 1
                    st.session_state.regenerate_mode = False
                    st.rerun()
            
            with col_count:
                st.markdown(f'<p style="color: #e6f7ff; text-align: center; font-weight: 600;">{st.session_state.current_message_index + 1}/{len(st.session_state.generated_messages)}</p>', unsafe_allow_html=True)
            
            # Refinement Mode
            if st.session_state.regenerate_mode:
                st.markdown("---")
                st.markdown('<h4 style="color: #e6f7ff;">Refine Message</h4>', unsafe_allow_html=True)
                
                with st.form("refinement_form"):
                    instructions = st.text_area(
                        "How would you like to improve this message?",
                        value=st.session_state.message_instructions,
                        placeholder="Example: Make more technical, Focus on AI experience, Make it shorter",
                        height=100
                    )
                    
                    col_ref1, col_ref2 = st.columns([2, 1])
                    
                    with col_ref1:
                        refine_submit = st.form_submit_button(
                            "Generate Refined Version",
                            use_container_width=True
                        )
                    
                    with col_ref2:
                        cancel_refine = st.form_submit_button(
                            "Cancel",
                            use_container_width=True
                        )
                    
                    if refine_submit and instructions:
                        with st.spinner("Refining message..."):
                            refined_options = analyze_and_generate_message(
                                st.session_state.profile_data,
                                st.session_state.sender_info,
                                groq_api_key,
                                instructions,
                                current_msg
                            )
                            
                            if refined_options:
                                new_msg = refined_options[0]
                                st.session_state.generated_messages.append({
                                    "text": new_msg,
                                    "char_count": len(new_msg),
                                    "option": len(st.session_state.generated_messages) + 1,
                                    "refinement_used": instructions
                                })
                                st.session_state.current_message_index = len(st.session_state.generated_messages) - 1
                                st.session_state.regenerate_mode = False
                                st.rerun()
                    
                    if cancel_refine:
                        st.session_state.regenerate_mode = False
                        st.rerun()
            
            # Message History
            if len(st.session_state.generated_messages) > 1:
                st.markdown("---")
                st.markdown('<h4 style="color: #e6f7ff; margin-bottom: 20px;">Message History</h4>', unsafe_allow_html=True)
                
                for idx, msg_obj in enumerate(st.session_state.generated_messages):
                    is_active = (idx == st.session_state.current_message_index)
                    
                    if isinstance(msg_obj, dict):
                        full_text = msg_obj.get("text", "")
                        refinement = msg_obj.get("refinement_used", "")
                    else:
                        full_text = str(msg_obj)
                        refinement = ""
                    
                    # Clean preview text
                    text_preview = full_text.replace('\n', ' ').strip()
                    text_preview = text_preview[:60] + "..." if len(text_preview) > 60 else text_preview
                    
                    # Create button for each version
                    if st.button(
                        f"Version {idx + 1}: {text_preview}", 
                        key=f"hist_btn_{idx}", 
                        use_container_width=True,
                        help="Click to view this version"
                    ):
                        st.session_state.current_message_index = idx
                        st.session_state.regenerate_mode = False
                        st.rerun()
                    
                    # Active indicator
                    if is_active:
                        st.markdown(
                            f'<div style="margin-top: -15px; margin-bottom: 10px; padding: 5px 15px; background: #00b4d8; border-radius: 0 0 10px 10px; font-size: 0.7rem; color: white; font-weight: bold; text-align: center;">CURRENTLY VIEWING</div>', 
                            unsafe_allow_html=True
                        )
        
        else:
            st.markdown('''
            <div class="card-3d" style="text-align: center; padding: 60px 30px;">
                <h4 style="color: #e6f7ff; margin-bottom: 15px;">Generate Your First Message</h4>
                <p style="color: #8892b0; max-width: 400px; margin: 0 auto;">
                    Click Generate AI Message to create personalized messages that build depth on their role and include your expertise.
                </p>
            </div>
            ''', unsafe_allow_html=True)
    
    with tab2:
        st.markdown('<h3 style="color: #e6f7ff; margin-bottom: 25px;">Research Brief</h3>', unsafe_allow_html=True)
        st.markdown('<div class="card-3d">', unsafe_allow_html=True)
        st.markdown(st.session_state.research_brief)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab3:
        st.markdown('<h3 style="color: #e6f7ff; margin-bottom: 25px;">Profile Data</h3>', unsafe_allow_html=True)
        
        # Display Recent Posts
        st.markdown('<h4 style="color: #00ffd0;">Recent LinkedIn Posts (Last 30 Days)</h4>', unsafe_allow_html=True)
        posts = st.session_state.profile_data.get('posts', [])
        
        if posts:
            for i, post in enumerate(posts):
                with st.expander(f"Post {i+1} - {datetime.fromtimestamp(post.get('timestamp', 0)/1000).strftime('%Y-%m-%d') if post.get('timestamp') else 'Recent'}", expanded=(i==0)):
                    st.markdown(f"**Content:**")
                    st.write(post.get('text', 'No text content'))
                    if post.get('url'):
                        st.markdown(f"**URL:** {post.get('url')}")
        else:
            st.info("No professional posts found in the last 30 days.")
        
        st.markdown("---")
        with st.expander("View Full Prospect Data", expanded=False):
            st.json(st.session_state.profile_data)

else:
    if not st.session_state.sender_info:
        st.markdown('''
        <div style="text-align: center; padding: 80px 20px;">
            <div style="position: relative; display: inline-block; margin-bottom: 40px;">
                <div style="width: 120px; height: 120px; background: linear-gradient(135deg, #00b4d8, #00ffd0); border-radius: 30px; transform: rotate(45deg); margin: 0 auto 40px; position: relative; box-shadow: 0 20px 60px rgba(0, 180, 216, 0.4);">
                </div>
            </div>
            <h2 style="color: #e6f7ff; margin-bottom: 20px; font-size: 2.5rem;">Get Started with LINZY</h2>
            <p style="color: #8892b0; max-width: 600px; margin: 0 auto 50px; line-height: 1.8; font-size: 1.1rem;">
                To generate personalized LinkedIn messages, please start by entering your information above.
                Your "What You Do" will be used in the second line of every message.
            </p>
            <div style="display: flex; justify-content: center; gap: 30px; flex-wrap: wrap;">
                <div style="background: rgba(255, 255, 255, 0.03); padding: 25px; border-radius: 20px; width: 200px; border: 1px solid rgba(0, 180, 216, 0.1);">
                    <h4 style="color: #e6f7ff; margin-bottom: 10px;">1. Your Info</h4>
                    <p style="color: #8892b0; font-size: 0.9rem;">Enter your name and what you do</p>
                </div>
                <div style="background: rgba(255, 255, 255, 0.03); padding: 25px; border-radius: 20px; width: 200px; border: 1px solid rgba(0, 180, 216, 0.1);">
                    <h4 style="color: #e6f7ff; margin-bottom: 10px;">2. Prospect Profile</h4>
                    <p style="color: #8892b0; font-size: 0.9rem;">Analyze the prospect LinkedIn profile</p>
                </div>
                <div style="background: rgba(255, 255, 255, 0.03); padding: 25px; border-radius: 20px; width: 200px; border: 1px solid rgba(0, 180, 216, 0.1);">
                    <h4 style="color: #e6f7ff; margin-bottom: 10px;">3. Generate</h4>
                    <p style="color: #8892b0; font-size: 0.9rem;">AI creates messages with role depth</p>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)
    else:
        st.info("Enter a prospect LinkedIn URL above and click Analyze Prospect to get started.")

st.markdown('</div>', unsafe_allow_html=True)

# --- Footer ---
st.markdown("---")
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    st.markdown('<p style="color: #8892b0; font-size: 0.9rem;">Linzy v3.0 | AI LinkedIn Messaging</p>', unsafe_allow_html=True)
with col_f2:
    st.markdown(f'<p style="color: #8892b0; font-size: 0.9rem; text-align: center;">{datetime.now().strftime("%H:%M:%S")}</p>', unsafe_allow_html=True)
with col_f3:
    if st.session_state.profile_data:
        name = "Prospect Loaded"
        if isinstance(st.session_state.profile_data, dict):
            if 'fullname' in st.session_state.profile_data:
                name = st.session_state.profile_data['fullname'][:25]
        st.markdown(f'<p style="color: #8892b0; font-size: 0.9rem; text-align: right;">Prospect: {name}</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p style="color: #8892b0; font-size: 0.9rem; text-align: right;">Status: Ready</p>', unsafe_allow_html=True)
