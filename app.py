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
    Generate LinkedIn messages in the concise, professional style of the samples.
    Returns list of 3 complete message options (200-300 characters).
    """
    try:
        # 1. EXTRACT PROSPECT DATA
        prospect_name = "there"
        prospect_role = ""
        prospect_company = ""
        
        if isinstance(prospect_data, dict):
            # Extract name (first name only)
            if prospect_data.get('fullname'):
                name_parts = prospect_data['fullname'].split()
                prospect_name = name_parts[0] if name_parts else "there"
            elif prospect_data.get('basic_info') and prospect_data['basic_info'].get('fullname'):
                name_parts = prospect_data['basic_info']['fullname'].split()
                prospect_name = name_parts[0] if name_parts else "there"
            
            # Extract current position
            if prospect_data.get('headline'):
                headline = prospect_data['headline']
                if ' at ' in headline:
                    prospect_role = headline.split(' at ')[0].strip()
                    prospect_company = headline.split(' at ')[1].strip().split(' | ')[0].split(' - ')[0]
                elif ' - ' in headline:
                    parts = headline.split(' - ')
                    if len(parts) >= 2:
                        prospect_role = parts[0].strip()
                        prospect_company = parts[1].strip()
            
            # Fallback to experience
            if not prospect_role and prospect_data.get('experience'):
                experiences = prospect_data.get('experience', [])
                if experiences and len(experiences) > 0:
                    exp = experiences[0]
                    prospect_role = exp.get('title', '')
                    prospect_company = exp.get('company', '')
        
        # 2. EXTRACT RECENT POST (FIRST 60 CHARS)
        recent_post_topic = ""
        if isinstance(prospect_data, dict):
            posts = prospect_data.get('posts', [])
            if posts and len(posts) > 0 and isinstance(posts[0], dict):
                post_text = posts[0].get('text', '')
                if post_text:
                    # Clean and shorten
                    clean_text = post_text.replace('\n', ' ').strip()
                    recent_post_topic = clean_text[:60] + "..." if len(clean_text) > 60 else clean_text
        
        # 3. EXTRACT SENDER INFO
        sender_name = sender_info.get('name', 'Professional')
        sender_first_name = sender_name.split()[0] if sender_name else "Professional"
        sender_role_desc = sender_info.get('role_desc', '')
        
        # 4. SIMPLE, DIRECT PROMPT MATCHING SAMPLE STYLE
        system_prompt = f'''You are an expert LinkedIn message writer. Generate 3 different connection requests in the EXACT style of these examples:

EXAMPLE MESSAGES:
1. "Hi Maria,
Your role managing wire ops and branch controls at Banc of California builds on deep experience across audits, transfers, and team operations. I focus on automating servicing workflows to reduce risk and improve turnaround. Would be glad to connect.
Best, Joseph"

2. "Hi Eric,
Your work driving multi-year business transformative initiatives caught my eye. I've been connecting with peers navigating enterprise shifts while aligning delivery with strategy. Would love to connect and trade insights.
Best, Joseph"

3. "Hi Kathleen,
Guiding IT at FirstBank while navigating long-term tech evolution must be in equal parts challenging & exciting. Coming from the same ecosystem, I'd love to connect.
Best, Joseph"

RULES:
- Each message 200-300 characters MAX
- First line: "Hi [First Name],"
- Second line: Specific hook about their role/work (not generic)
- Third line: Brief mention of your work: "I focus on..." or "I've been exploring..." or "I work with..."
- Fourth line: Simple connection request: "Would be glad to connect." or "Thought it'd be great to connect." or "Let's connect."
- Signature: "Best, [Your First Name]"
- NO flattery, NO lengthy explanations, NO buzzwords
- If mentioning a post: "I saw your post about [topic]..." or "Noticed your focus on [topic]..."
- Sound like a peer, not a salesperson

PROSPECT:
Name: {prospect_name}
Role: {prospect_role or 'their role'}
Company: {prospect_company or 'their company'}
Recent Post: {recent_post_topic or 'None'}

YOU:
Name: {sender_first_name}
What you do: {sender_role_desc}

Generate 3 different messages following EXACTLY the structure and style above. Keep them concise and professional.'''

        # 5. USER PROMPT FOR REFINEMENT OR NEW
        if user_instructions and previous_message:
            user_prompt = f'''Refine this message: "{previous_message[:150]}"

Instructions: {user_instructions}

Generate 3 refined versions in the same concise style.'''
        else:
            user_prompt = '''Generate 3 connection messages following the style and rules above.'''
        
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
            "max_tokens": 1000,
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
            
            # SIMPLE PARSING: Look for messages starting with "Hi "
            messages = []
            lines = content.strip().split('\n')
            current_message = []
            collecting = False
            
            for line in lines:
                line = line.strip()
                
                # Start of a new message
                if line.startswith(f"Hi {prospect_name},") or line.startswith(f'"Hi {prospect_name},'):
                    if current_message and len(' '.join(current_message)) > 100:
                        msg_text = '\n'.join(current_message).strip()
                        messages.append(msg_text)
                    current_message = [line]
                    collecting = True
                elif collecting and line:
                    current_message.append(line)
                    # Check if we've reached the signature
                    if line.startswith("Best,") and sender_first_name.lower() in line.lower():
                        msg_text = '\n'.join(current_message).strip()
                        messages.append(msg_text)
                        current_message = []
                        collecting = False
                elif line.startswith('"Hi ') or line.startswith('1. "Hi ') or line.startswith('2. "Hi ') or line.startswith('3. "Hi '):
                    # Alternative format
                    if current_message and len(' '.join(current_message)) > 100:
                        msg_text = '\n'.join(current_message).strip()
                        messages.append(msg_text)
                    current_message = [line.replace('"', '').replace('1. ', '').replace('2. ', '').replace('3. ', '')]
                    collecting = True
            
            # Don't forget the last message
            if current_message and len(' '.join(current_message)) > 100:
                msg_text = '\n'.join(current_message).strip()
                messages.append(msg_text)
            
            # Clean and ensure proper formatting
            clean_messages = []
            for msg in messages:
                # Remove quotes if present
                msg = msg.strip('"')
                
                # Ensure proper signature
                if not msg.strip().endswith(f"Best,\n{sender_first_name}"):
                    if f"Best, {sender_first_name}" in msg:
                        # Convert to multiline
                        msg = msg.replace(f"Best, {sender_first_name}", f"Best,\n{sender_first_name}")
                    elif not msg.endswith(f"Best,\n{sender_first_name}"):
                        # Add signature
                        msg = f"{msg}\nBest,\n{sender_first_name}"
                
                # Remove any trailing quotes or numbers
                msg = msg.replace('1. ', '').replace('2. ', '').replace('3. ', '').strip()
                
                if len(msg) > 100:
                    clean_messages.append(msg)
            
            # Return exactly 3 messages
            if len(clean_messages) >= 3:
                return clean_messages[:3]
            elif clean_messages:
                # Add fallback messages to reach 3
                needed = 3 - len(clean_messages)
                fallbacks = generate_exact_style_fallback(prospect_name, sender_first_name, sender_role_desc, prospect_role, prospect_company)
                return clean_messages + fallbacks[:needed]
            else:
                return generate_exact_style_fallback(prospect_name, sender_first_name, sender_role_desc, prospect_role, prospect_company)
        
        # Fallback
        return generate_exact_style_fallback(prospect_name, sender_first_name, sender_role_desc, prospect_role, prospect_company)
        
    except Exception as e:
        return generate_exact_style_fallback("there", "Professional", sender_info.get('role_desc', ''), "their role", "their company")

def generate_exact_style_fallback(prospect_name: str, sender_first_name: str, 
                                sender_role_desc: str, prospect_role: str, prospect_company: str) -> list:
    """Generate fallback messages in the exact style of the samples."""
    
    # Templates matching the sample style
    templates = [
        f"""Hi {prospect_name},
Your role {f"as {prospect_role}" if prospect_role else "in your position"} {f"at {prospect_company}" if prospect_company else ""} caught my attention. {sender_role_desc or "I focus on streamlining operations"}. Would be glad to connect.
Best,
{sender_first_name}""",
        
        f"""Hi {prospect_name},
{f"Your work at {prospect_company}" if prospect_company else "Your professional work"} aligns with industry shifts I've been following. {sender_role_desc or "I'm exploring how automation is reshaping workflows"}. Thought it'd be great to connect.
Best,
{sender_first_name}""",
        
        f"""Hi {prospect_name},
{f"Your focus on {prospect_role.lower()}" if prospect_role else "Your approach to professional challenges"} resonates with my work. {sender_role_desc or "I help streamline operations through technology"}. Let's connect and exchange perspectives.
Best,
{sender_first_name}"""
    ]
    
    return templates[:3]
                                    
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
    .message-card {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 20px;
    padding: 25px;
    border: 1px solid rgba(0, 180, 216, 0.1);
    height: 100%;
    display: flex;
    flex-direction: column;
    transition: all 0.3s ease;
}

.message-card:hover {
    border-color: rgba(0, 180, 216, 0.3);
    transform: translateY(-5px);
}

.message-card.selected {
    border-color: #00b4d8;
    box-shadow: 0 0 30px rgba(0, 180, 216, 0.2);
}

.message-content {
    flex-grow: 1;
    overflow-y: auto;
    margin: 20px 0;
    padding: 15px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.05);
}

.message-actions {
    display: flex;
    gap: 10px;
    margin-top: auto;
}

.btn-copy {
    background: rgba(0, 180, 216, 0.1);
    border: 1px solid rgba(0, 180, 216, 0.3);
    color: #00b4d8;
    padding: 10px 20px;
    border-radius: 10px;
    cursor: pointer;
    font-size: 0.9rem;
    transition: all 0.3s ease;
    width: 100%;
}

.btn-copy:hover {
    background: rgba(0, 180, 216, 0.2);
    border-color: #00b4d8;
}

.btn-select {
    background: linear-gradient(135deg, #00b4d8 0%, #0077b6 100%);
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 10px;
    cursor: pointer;
    font-size: 0.9rem;
    transition: all 0.3s ease;
    width: 100%;
}

.btn-select:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 25px rgba(0, 180, 216, 0.3);
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

        # Generation button
        if st.button("Generate AI Messages", use_container_width=True, key="generate_message"):
            with st.spinner("Creating personalized messages..."):
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
                    st.rerun()

        # Display all generated messages in separate columns
        if len(st.session_state.generated_messages) > 0:
            st.markdown("---")
            st.markdown('<h4 style="color: #e6f7ff; margin-bottom: 20px;">Generated Message Options</h4>', unsafe_allow_html=True)

            # Create 3 columns for the 3 messages
            col1, col2, col3 = st.columns(3, gap="large")

            columns = [col1, col2, col3]

            for i, msg_data in enumerate(st.session_state.generated_messages[:3]):  # Only show first 3
                with columns[i]:
                    msg_text = msg_data["text"]
                    char_count = msg_data["char_count"]

                    # Message card
                    st.markdown(f'''
                    <div class="card-3d" style="height: 420px; display: flex; flex-direction: column;">
                        <div style="margin-bottom: 15px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <h4 style="color: #00ffd0; margin: 0;">Option {msg_data['option']}</h4>
                                <span style="color: #8892b0; font-size: 0.85rem;">
                                    {char_count} chars
                                </span>
                            </div>
                        </div>

                        <div style="flex-grow: 1; overflow-y: auto; margin-bottom: 20px;">
                            <pre style="white-space: pre-wrap; font-family: 'Inter', sans-serif; line-height: 1.6; margin: 0; color: #e6f7ff; font-size: 0.95rem; word-wrap: break-word;">
{msg_text}
                            </pre>
                        </div>

                        <div style="margin-top: auto;">
                            <div style="display: flex; gap: 10px; margin-bottom: 10px;">
                                <button onclick="navigator.clipboard.writeText(`{msg_text.replace('`', '\\`')}`)" style="background: rgba(0, 180, 216, 0.1); border: 1px solid rgba(0, 180, 216, 0.3); color: #00b4d8; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 0.9rem; width: 100%;">
                                    <i class="fas fa-copy"></i> Copy
                                </button>
                            </div>
                            <div style="text-align: center;">
                                <button onclick="selectMessage({i})" style="background: linear-gradient(135deg, #00b4d8 0%, #0077b6 100%); color: white; border: none; padding: 10px; border-radius: 8px; cursor: pointer; font-size: 0.9rem; width: 100%;">
                                    Select & Refine
                                </button>
                            </div>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)

            # Add JavaScript for copy and select functionality
            st.markdown('''
            <script>
            function copyToClipboard(text) {
                navigator.clipboard.writeText(text).then(() => {
                    alert('Message copied to clipboard!');
                });
            }

            function selectMessage(index) {
                // This would trigger a Streamlit rerun with the selected message index
                // In a real implementation, you'd use Streamlit's JS to Python bridge
                alert('Selected message ' + (index + 1) + ' for refinement');
            }
            </script>
            ''', unsafe_allow_html=True)

            # Refinement section
            st.markdown("---")
            st.markdown('<h4 style="color: #e6f7ff; margin-bottom: 20px;">Refine Selected Message</h4>', unsafe_allow_html=True)

            # Message selection dropdown
            message_options = [f"Option {i+1}: {msg['text'][:80]}..." for i, msg in enumerate(st.session_state.generated_messages)]

            col_ref1, col_ref2 = st.columns([3, 1])

            with col_ref1:
                selected_option = st.selectbox(
                    "Select a message to refine:",
                    options=range(len(st.session_state.generated_messages)),
                    format_func=lambda x: message_options[x],
                    key="selected_message_refine"
                )

            with col_ref2:
                refine_clicked = st.button("Refine This Message", use_container_width=True, key="refine_trigger")

            # Refinement form
            if refine_clicked or st.session_state.get('refine_mode', False):
                st.session_state.refine_mode = True

                selected_msg = st.session_state.generated_messages[selected_option]

                with st.form("refinement_form"):
                    instructions = st.text_area(
                        "How would you like to refine this message?",
                        value=st.session_state.get('refine_instructions', ''),
                        placeholder="Example: Make it more technical, focus on AI experience, make it shorter...",
                        height=100,
                        key="refine_instructions_input"
                    )

                    col_submit, col_cancel = st.columns([1, 1])

                    with col_submit:
                        submit_refine = st.form_submit_button(
                            "Generate Refined Version",
                            use_container_width=True
                        )

                    with col_cancel:
                        cancel_refine = st.form_submit_button(
                            "Cancel",
                            use_container_width=True
                        )

                    if submit_refine and instructions:
                        with st.spinner("Refining message..."):
                            refined_options = analyze_and_generate_message(
                                st.session_state.profile_data,
                                st.session_state.sender_info,
                                groq_api_key,
                                instructions,
                                selected_msg["text"]
                            )

                            if refined_options:
                                # Add the refined message to the list
                                new_msg = refined_options[0]
                                st.session_state.generated_messages.append({
                                    "text": new_msg,
                                    "char_count": len(new_msg),
                                    "option": len(st.session_state.generated_messages) + 1,
                                    "refined_from": selected_option + 1
                                })
                                st.session_state.refine_mode = False
                                st.success("Message refined successfully!")
                                st.rerun()

                    if cancel_refine:
                        st.session_state.refine_mode = False
                        st.rerun()

            # Message history accordion
            if len(st.session_state.generated_messages) > 3:
                with st.expander("Message History (All Versions)", expanded=False):
                    for idx, msg_obj in enumerate(st.session_state.generated_messages):
                        if isinstance(msg_obj, dict):
                            text = msg_obj.get("text", "")
                            refined_from = msg_obj.get("refined_from", "")

                            # Clean preview
                            preview = text.replace('\n', ' ').strip()[:100] + "..." if len(text) > 100 else text

                            col_hist1, col_hist2, col_hist3 = st.columns([3, 1, 1])

                            with col_hist1:
                                st.markdown(f"**Version {idx + 1}**" + (f" (Refined from Option {refined_from})" if refined_from else ""))
                                st.markdown(f'<span style="color: #8892b0; font-size: 0.9rem;">{preview}</span>', unsafe_allow_html=True)

                            with col_hist2:
                                if st.button("View", key=f"view_hist_{idx}", use_container_width=True):
                                    # You could implement a detailed view here
                                    st.code(text, language=None)

                            with col_hist3:
                                if st.button("Use", key=f"use_hist_{idx}", use_container_width=True):
                                    st.info(f"Message {idx + 1} selected for use")

                            st.markdown("---")

        else:
            # Empty state when no messages generated
            st.markdown('''
            <div class="card-3d" style="text-align: center; padding: 60px 30px;">
                <div style="font-size: 4rem; margin-bottom: 20px; color: #00b4d8;">
                    <i class="fas fa-comments"></i>
                </div>
                <h4 style="color: #e6f7ff; margin-bottom: 15px;">Generate Your First Messages</h4>
                <p style="color: #8892b0; max-width: 500px; margin: 0 auto 30px;">
                    Click the button above to generate 3 personalized LinkedIn message options. Each message will be displayed separately for easy comparison.
                </p>
                <div style="display: flex; justify-content: center; gap: 20px; margin-top: 40px;">
                    <div style="text-align: center;">
                        <div style="width: 60px; height: 60px; background: rgba(0, 180, 216, 0.1); border-radius: 15px; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px;">
                            <span style="color: #00b4d8; font-size: 1.5rem;">1</span>
                        </div>
                        <span style="color: #8892b0; font-size: 0.9rem;">Generate 3 Options</span>
                    </div>
                    <div style="text-align: center;">
                        <div style="width: 60px; height: 60px; background: rgba(0, 180, 216, 0.1); border-radius: 15px; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px;">
                            <span style="color: #00b4d8; font-size: 1.5rem;">2</span>
                        </div>
                        <span style="color: #8892b0; font-size: 0.9rem;">Compare & Select</span>
                    </div>
                    <div style="text-align: center;">
                        <div style="width: 60px; height: 60px; background: rgba(0, 180, 216, 0.1); border-radius: 15px; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px;">
                            <span style="color: #00b4d8; font-size: 1.5rem;">3</span>
                        </div>
                        <span style="color: #8892b0; font-size: 0.9rem;">Refine & Copy</span>
                    </div>
                </div>
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
