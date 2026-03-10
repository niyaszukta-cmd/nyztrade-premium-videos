"""
NYZTrade Premium Video Streaming Platform
- OTP Login via Mobile Number (Twilio SMS)
- Screenshot/Recording Prevention via CSS/JS overlays
- HD Video Upload & Streaming
- Dynamic Watermarking per session
"""

import streamlit as st
import os
import uuid
import hashlib
import json
import random
import time
import base64
import hmac
from pathlib import Path
from datetime import datetime, timedelta

# ─── Twilio (graceful fallback to dev mode if not installed) ─────────────────
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NYZTrade Premium",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Constants ────────────────────────────────────────────────────────────────
VIDEO_DIR  = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)
USERS_FILE = Path("users.json")
SECRET_KEY = os.environ.get("SECRET_KEY", "nyztrade-secret-2024")

# Twilio credentials – set as env vars OR Streamlit secrets
def _secret(key, default=""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID",  _secret("TWILIO_ACCOUNT_SID"))
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN",   _secret("TWILIO_AUTH_TOKEN"))
TWILIO_FROM  = os.environ.get("TWILIO_PHONE_NUMBER", _secret("TWILIO_PHONE_NUMBER"))

OTP_EXPIRY_SECONDS = 300   # 5 minutes
OTP_MAX_ATTEMPTS   = 3

# ─── Anti-Capture CSS + JS ────────────────────────────────────────────────────
ANTI_CAPTURE_CSS_JS = """
<style>
  * {
    -webkit-user-select: none !important;
    -moz-user-select: none !important;
    -ms-user-select: none !important;
    user-select: none !important;
  }
  video {
    pointer-events: none !important;
    -webkit-user-drag: none !important;
  }
  .watermark {
    position: fixed;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%) rotate(-30deg);
    font-size: 1.8rem;
    color: rgba(255,165,0,0.12);
    font-weight: bold;
    pointer-events: none;
    z-index: 10000;
    white-space: nowrap;
    letter-spacing: 4px;
  }
  body { -webkit-touch-callout: none; }
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }
</style>

<script>
(function() {
  // Disable right-click
  document.addEventListener('contextmenu', function(e) { e.preventDefault(); return false; });

  // Block capture & devtools shortcuts
  document.addEventListener('keydown', function(e) {
    var blocked = [
      e.key === 'PrintScreen',
      e.key === 'F12',
      (e.ctrlKey && e.shiftKey && ['I','i','J','j','C','c'].includes(e.key)),
      (e.ctrlKey && ['u','U','s','S','p','P'].includes(e.key)),
      (e.metaKey && ['u','U','s','S','p','P'].includes(e.key)),
    ];
    if (blocked.some(Boolean)) { e.preventDefault(); e.stopPropagation(); return false; }
  });

  // Pause video on tab hide
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) document.querySelectorAll('video').forEach(function(v){ v.pause(); });
  });

  // DevTools size heuristic
  setInterval(function() {
    if (window.outerWidth - window.innerWidth > 160 || window.outerHeight - window.innerHeight > 160) {
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0a0a0a;color:#ff4444;font-size:2rem;font-family:sans-serif;">🔒 Access Denied: Developer Tools Detected</div>';
    }
  }, 1500);

  // Block drag on media
  document.addEventListener('dragstart', function(e) {
    if (['VIDEO','IMG'].includes(e.target.tagName)) e.preventDefault();
  });
})();
</script>
"""

# ─── OTP Helpers ─────────────────────────────────────────────────────────────

def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_sms(phone: str, otp: str):
    """Send OTP via Twilio. Returns (success: bool, message: str)."""
    if not TWILIO_AVAILABLE:
        return False, "twilio_not_installed"
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM]):
        return False, "twilio_not_configured"
    try:
        client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            body=f"NYZTrade Premium: Your OTP is {otp}. Valid for 5 minutes. Do NOT share this code.",
            from_=TWILIO_FROM,
            to=phone
        )
        return True, "sent"
    except Exception as e:
        return False, str(e)

def normalize_phone(phone: str) -> str:
    """Convert any Indian/international format to E.164."""
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not p.startswith("+"):
        if p.startswith("0"):
            p = "+91" + p[1:]
        elif len(p) == 10:
            p = "+91" + p
        else:
            p = "+" + p
    return p

# ─── User Store ───────────────────────────────────────────────────────────────

def load_users():
    if USERS_FILE.exists():
        with open(USERS_FILE) as f:
            return json.load(f)
    # Seed with demo accounts (replace with real numbers)
    default = {
        "+919876543210": {
            "role": "admin",
            "name": "Admin (Niyas)",
            "email": "admin@nyztrade.com",
            "active": True
        },
        "+919876543211": {
            "role": "premium",
            "name": "Premium Client 1",
            "email": "client1@example.com",
            "active": True
        },
        "+919876543212": {
            "role": "premium",
            "name": "Premium Client 2",
            "email": "client2@example.com",
            "active": True
        },
    }
    with open(USERS_FILE, "w") as f:
        json.dump(default, f, indent=2)
    return default

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

# ─── Video Store ──────────────────────────────────────────────────────────────

def get_video_list():
    meta_file = VIDEO_DIR / "metadata.json"
    if meta_file.exists():
        with open(meta_file) as f:
            return json.load(f)
    return {}

def save_video_meta(meta):
    meta_file = VIDEO_DIR / "metadata.json"
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)

def get_video_b64(path: Path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ─── Protected Video Player ───────────────────────────────────────────────────

def render_protected_video(video_path: Path, watermark_text: str):
    ext  = video_path.suffix.lower().lstrip(".")
    mime = {"mp4":"video/mp4","webm":"video/webm","ogv":"video/ogg","mov":"video/mp4"}.get(ext,"video/mp4")
    b64  = get_video_b64(video_path)
    src  = f"data:{mime};base64,{b64}"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""
    <div style="position:relative;width:100%;">
      <!-- Dynamic watermark -->
      <div style="position:absolute;top:50%;left:50%;
           transform:translate(-50%,-50%) rotate(-25deg);
           font-size:1.4rem;color:rgba(255,140,0,0.18);
           font-weight:900;pointer-events:none;z-index:500;
           white-space:nowrap;letter-spacing:3px;font-family:monospace;">
        {watermark_text} &nbsp; {ts}
      </div>
      <!-- Transparent anti-capture overlay -->
      <div style="position:absolute;top:0;left:0;width:100%;height:100%;
           z-index:400;background:transparent;pointer-events:none;"></div>
      <!-- Player -->
      <video id="nyztrade-player" controls
        controlsList="nodownload nofullscreen noremoteplayback"
        disablePictureInPicture disableRemotePlayback
        style="width:100%;border-radius:8px;outline:none;"
        oncontextmenu="return false;">
        <source src="{src}" type="{mime}">
        Your browser does not support HTML5 video.
      </video>
    </div>
    <script>
    (function(){{
      var p = document.getElementById('nyztrade-player');
      if (!p) return;
      document.addEventListener('visibilitychange', function(){{ if(document.hidden) p.pause(); }});
      document.addEventListener('keyup', function(e){{
        if(e.key === 'PrintScreen'){{
          p.pause();
          p.style.filter = 'blur(20px)';
          setTimeout(function(){{ p.style.filter='none'; }}, 3000);
        }}
      }});
    }})();
    </script>
    """
    st.components.v1.html(html, height=500, scrolling=False)

# ─── Login Screen (OTP Flow) ──────────────────────────────────────────────────

def login_screen(users):
    st.markdown(ANTI_CAPTURE_CSS_JS, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.3, 1])
    with col2:
        st.markdown("""
        <div style='text-align:center;padding:2rem 0 1.2rem;'>
          <span style='font-size:3rem;'>🎬</span>
          <h1 style='color:#FFA500;margin:0.3rem 0;font-size:1.9rem;letter-spacing:1px;'>NYZTrade Premium</h1>
          <p style='color:#555;font-size:0.85rem;margin:0;'>Exclusive Content for Verified Premium Clients</p>
        </div>
        """, unsafe_allow_html=True)

        # ────────────────────────────────────────────────────────────
        # STEP 1 — Phone Number Entry
        # ────────────────────────────────────────────────────────────
        if not st.session_state.get("otp_sent"):

            st.markdown("""
            <div style="background:#111;border:1px solid #2a2a2a;border-radius:10px;
                 padding:1.2rem 1.4rem;margin-bottom:1rem;">
              <p style="color:#888;font-size:0.82rem;margin:0 0 0.8rem 0;">
                📲 Enter your registered mobile number to receive a one-time password via SMS.
              </p>
            </div>
            """, unsafe_allow_html=True)

            with st.form("phone_form"):
                raw_phone = st.text_input(
                    "📱 Mobile Number",
                    placeholder="+91 98765 43210  or  9876543210",
                    help="Number registered with NYZTrade Premium"
                )
                send_btn = st.form_submit_button("📨 Send OTP", use_container_width=True, type="primary")

            if send_btn:
                phone = normalize_phone(raw_phone) if raw_phone.strip() else ""
                if len(phone) < 10:
                    st.error("Please enter a valid mobile number.")
                elif phone not in users:
                    st.error("❌ Number not registered. Contact NYZTrade support.")
                elif not users[phone].get("active", True):
                    st.error("🚫 Account suspended. Contact NYZTrade support.")
                else:
                    otp  = generate_otp()
                    sent, msg = send_otp_sms(phone, otp)

                    st.session_state["otp_phone"]    = phone
                    st.session_state["otp_code"]     = otp
                    st.session_state["otp_sent_at"]  = time.time()
                    st.session_state["otp_attempts"] = 0
                    st.session_state["otp_sent"]     = True

                    if sent:
                        st.success(f"✅ OTP sent to {phone[:4]}****{phone[-3:]}. Valid for 5 minutes.")
                    elif msg == "twilio_not_configured":
                        st.warning("⚙️ **Dev Mode** — Twilio credentials not set.")
                        st.info(f"🔑 OTP (dev only): **{otp}**")
                    elif msg == "twilio_not_installed":
                        st.warning("⚙️ **Dev Mode** — `twilio` package not installed.")
                        st.info(f"🔑 OTP (dev only): **{otp}**")
                    else:
                        st.error(f"SMS failed: {msg}")
                    st.rerun()

        # ────────────────────────────────────────────────────────────
        # STEP 2 — OTP Verification
        # ────────────────────────────────────────────────────────────
        else:
            phone    = st.session_state["otp_phone"]
            sent_at  = st.session_state["otp_sent_at"]
            attempts = st.session_state.get("otp_attempts", 0)
            elapsed  = time.time() - sent_at
            remaining = max(0, int(OTP_EXPIRY_SECONDS - elapsed))
            masked   = f"{phone[:4]}****{phone[-3:]}"

            # Countdown bar
            progress = remaining / OTP_EXPIRY_SECONDS
            bar_color = "#FFA500" if progress > 0.4 else "#ff4444"
            st.markdown(f"""
            <div style="background:#111;border:1px solid #2a2a2a;border-radius:10px;
                 padding:1rem 1.2rem;margin-bottom:0.8rem;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                <span style="color:#888;font-size:0.82rem;">📨 OTP sent to <b style="color:#ccc;">{masked}</b></span>
                <span style="color:{bar_color};font-weight:700;font-size:1rem;">⏱ {remaining}s</span>
              </div>
              <div style="background:#222;border-radius:4px;height:5px;">
                <div style="background:{bar_color};width:{int(progress*100)}%;height:5px;border-radius:4px;
                     transition:width 1s linear;"></div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            if remaining == 0:
                st.error("⏰ OTP expired.")
                if st.button("🔄 Request New OTP", use_container_width=True, type="primary"):
                    for k in ["otp_sent","otp_code","otp_sent_at","otp_attempts","otp_phone"]:
                        st.session_state.pop(k, None)
                    st.rerun()
                return

            if attempts >= OTP_MAX_ATTEMPTS:
                st.error("🚫 Too many incorrect attempts. Request a new OTP.")
                if st.button("🔄 Request New OTP", use_container_width=True, type="primary"):
                    for k in ["otp_sent","otp_code","otp_sent_at","otp_attempts","otp_phone"]:
                        st.session_state.pop(k, None)
                    st.rerun()
                return

            st.markdown(f"#### 🔑 Enter 6-Digit OTP  &nbsp; <span style='color:#555;font-size:0.75rem;'>Attempt {attempts+1}/{OTP_MAX_ATTEMPTS}</span>", unsafe_allow_html=True)

            with st.form("otp_form"):
                entered_otp = st.text_input(
                    "OTP",
                    placeholder="• • • • • •",
                    max_chars=6,
                    label_visibility="collapsed"
                )
                verify_btn = st.form_submit_button("✅ Verify & Login", use_container_width=True, type="primary")

            if verify_btn:
                otp_clean = entered_otp.strip()
                if not otp_clean.isdigit() or len(otp_clean) != 6:
                    st.error("Please enter the 6-digit OTP received via SMS.")
                elif hmac.compare_digest(otp_clean, st.session_state["otp_code"]):
                    # ✅ Login successful
                    user_info = users[phone]
                    st.session_state["authenticated"] = True
                    st.session_state["username"]      = phone
                    st.session_state["role"]          = user_info["role"]
                    st.session_state["name"]          = user_info["name"]
                    st.session_state["session_id"]    = str(uuid.uuid4())[:8].upper()
                    for k in ["otp_sent","otp_code","otp_sent_at","otp_attempts","otp_phone"]:
                        st.session_state.pop(k, None)
                    st.rerun()
                else:
                    st.session_state["otp_attempts"] = attempts + 1
                    left = OTP_MAX_ATTEMPTS - attempts - 1
                    st.error(f"❌ Incorrect OTP. {left} attempt(s) remaining.")

            # Resend / Change number
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🔄 Resend OTP", use_container_width=True):
                    new_otp = generate_otp()
                    sent, msg = send_otp_sms(phone, new_otp)
                    st.session_state.update({
                        "otp_code": new_otp,
                        "otp_sent_at": time.time(),
                        "otp_attempts": 0
                    })
                    if sent:
                        st.success("✅ New OTP sent!")
                    elif msg in ("twilio_not_configured","twilio_not_installed"):
                        st.warning("Dev Mode")
                        st.info(f"🔑 New OTP: **{new_otp}**")
                    else:
                        st.error(f"SMS failed: {msg}")
                    st.rerun()
            with c2:
                if st.button("← Change Number", use_container_width=True):
                    for k in ["otp_sent","otp_code","otp_sent_at","otp_attempts","otp_phone"]:
                        st.session_state.pop(k, None)
                    st.rerun()

        st.markdown("""
        <div style='text-align:center;margin-top:1.8rem;color:#333;font-size:0.72rem;'>
          🔒 OTP-Secured &nbsp;|&nbsp; © NYZTrade Analytics Pvt. Ltd., Kerala
        </div>
        """, unsafe_allow_html=True)

# ─── Admin Panel ──────────────────────────────────────────────────────────────

def admin_panel(users):
    st.markdown("### 🛠️ Admin Panel")
    tab1, tab2, tab3 = st.tabs(["📤 Upload Video", "🎬 Manage Videos", "👥 Manage Clients"])

    with tab1:
        st.markdown("#### Upload HD Video")
        title       = st.text_input("Video Title", placeholder="Options Greeks Masterclass – Module 1")
        description = st.text_area("Description", height=80)
        category    = st.selectbox("Category", ["Options Trading","Stock Analysis","ESG Investing","Technical Analysis","Fundamental Analysis","General"])
        thumbnail   = st.text_input("Thumbnail URL (optional)")
        uploaded    = st.file_uploader("Upload HD Video", type=["mp4","webm","mov","mkv"],
                                       help="MP4/WebM/MOV/MKV — HD/4K, up to 2 GB")
        if uploaded and not title:
            st.warning("⚠️ Please enter a **Video Title** above to enable the Save button.")

        if uploaded:
            if st.button("💾 Save Video", use_container_width=True, type="primary", disabled=not title):
                vid_id    = str(uuid.uuid4())[:12]
                ext       = uploaded.name.split(".")[-1].lower()
                save_path = VIDEO_DIR / f"{vid_id}.{ext}"
                with st.spinner(f"Saving {uploaded.name} ({uploaded.size/1024/1024:.1f} MB)…"):
                    with open(save_path, "wb") as f:
                        f.write(uploaded.read())
                meta = get_video_list()
                meta[vid_id] = {
                    "title": title, "description": description, "category": category,
                    "filename": f"{vid_id}.{ext}",
                    "size_mb": round(uploaded.size/1024/1024, 2),
                    "uploaded_at": datetime.now().isoformat(),
                    "thumbnail": thumbnail,
                    "uploader": st.session_state["name"]
                }
                save_video_meta(meta)
                st.success(f"✅ '{title}' saved ({meta[vid_id]['size_mb']} MB)")
                st.balloons()

    with tab2:
        meta = get_video_list()
        if not meta:
            st.info("No videos uploaded yet.")
        else:
            for vid_id, info in meta.items():
                with st.expander(f"🎬 {info['title']} — {info['category']} ({info['size_mb']} MB)"):
                    st.write(f"**Uploaded:** {info['uploaded_at'][:10]}  |  **By:** {info.get('uploader','')}")
                    if st.button("🗑️ Delete", key=f"del_{vid_id}"):
                        fp = VIDEO_DIR / info["filename"]
                        if fp.exists(): fp.unlink()
                        del meta[vid_id]
                        save_video_meta(meta)
                        st.success("Deleted.")
                        st.rerun()

    with tab3:
        st.markdown("#### Registered Clients")
        for phone, info in users.items():
            cols = st.columns([2.5, 2, 2, 1, 1])
            cols[0].write(f"**{info.get('name','')}**")
            cols[1].write(phone)
            cols[2].write(info.get("email",""))
            cols[3].write("🛡️ Admin" if info["role"]=="admin" else "⭐ Premium")
            status = info.get("active", True)
            if cols[4].button("🔴 Suspend" if status else "🟢 Activate", key=f"tog_{phone}"):
                users[phone]["active"] = not status
                save_users(users)
                st.rerun()

        st.divider()
        st.markdown("#### ➕ Add New Premium Client")
        with st.form("add_client_form"):
            new_phone = st.text_input("Mobile Number", placeholder="+91 98765 43210")
            new_name  = st.text_input("Full Name")
            new_email = st.text_input("Email")
            new_role  = st.selectbox("Role", ["premium","admin"])
            if st.form_submit_button("➕ Add Client"):
                np = normalize_phone(new_phone) if new_phone.strip() else ""
                if not np or len(np) < 10:
                    st.error("Invalid number.")
                elif np in users:
                    st.error("Number already registered.")
                else:
                    users[np] = {"role":new_role,"name":new_name,"email":new_email,"active":True}
                    save_users(users)
                    st.success(f"✅ {new_name} ({np}) added.")
                    st.rerun()

# ─── Client Video View ────────────────────────────────────────────────────────

def client_view():
    meta       = get_video_list()
    username   = st.session_state["username"]
    session_id = st.session_state.get("session_id", "DEMO")
    wm         = f"NYZTrade | ****{username[-4:]} | {session_id}"

    categories   = list(set(v["category"] for v in meta.values())) if meta else []
    selected_cat = st.selectbox("📂 Filter by Category", ["All"] + sorted(categories))
    filtered     = {k:v for k,v in meta.items()
                    if selected_cat == "All" or v["category"] == selected_cat}

    if not filtered:
        st.info("🎬 No videos available yet. Check back soon!")
        return

    cols = st.columns(3)
    for i, (vid_id, info) in enumerate(filtered.items()):
        with cols[i % 3]:
            thumb = info.get("thumbnail") or "https://via.placeholder.com/320x180/0a0a0a/FFA500?text=▶+NYZTrade"
            st.markdown(f"""
            <div style="border:1px solid #2a2a2a;border-radius:10px;padding:0.5rem;
                 margin-bottom:0.5rem;background:#111;">
              <img src="{thumb}" style="width:100%;border-radius:6px;height:120px;object-fit:cover;"/>
              <p style="color:#FFA500;font-weight:700;margin:0.4rem 0 0.1rem;font-size:0.85rem;">{info['title']}</p>
              <p style="color:#555;font-size:0.72rem;margin:0;">{info['category']} | {info['size_mb']} MB</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("▶ Watch", key=f"watch_{vid_id}", use_container_width=True):
                st.session_state["active_video"] = vid_id

    if "active_video" in st.session_state:
        vid_id = st.session_state["active_video"]
        if vid_id in meta:
            info       = meta[vid_id]
            video_path = VIDEO_DIR / info["filename"]
            st.divider()
            st.markdown(f"### 🎬 {info['title']}")
            st.caption(f"📁 {info['category']}  |  📅 {info['uploaded_at'][:10]}  |  📦 {info['size_mb']} MB")
            if video_path.exists():
                with st.spinner("Loading protected stream…"):
                    render_protected_video(video_path, wm)
                st.markdown(f"""
                <div style="color:#333;font-size:0.7rem;text-align:center;margin-top:0.3rem;">
                  🔒 Watermarked & Protected &nbsp;|&nbsp; Session: {session_id}
                </div>""", unsafe_allow_html=True)
            else:
                st.error("Video file not found. Contact support.")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    users = load_users()
    st.markdown(ANTI_CAPTURE_CSS_JS, unsafe_allow_html=True)

    if not st.session_state.get("authenticated"):
        login_screen(users)
        return

    # App header
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
         background:linear-gradient(90deg,#0a0a0a,#181818);
         padding:0.8rem 1.5rem;border-bottom:2px solid #FFA500;
         margin-bottom:1rem;border-radius:0 0 8px 8px;">
      <div>
        <span style="color:#FFA500;font-size:1.4rem;font-weight:900;">🎬 NYZTrade Premium</span>
        <span style="color:#444;font-size:0.8rem;margin-left:1rem;">Exclusive Content Platform</span>
      </div>
      <div style="color:#666;font-size:0.8rem;text-align:right;">
        📱 ****{st.session_state['username'][-4:]} &nbsp;|&nbsp;
        <span style="color:#FFA500;">{'🛡️ ADMIN' if st.session_state['role']=='admin' else '⭐ PREMIUM'}</span>
        &nbsp;|&nbsp; {st.session_state['name']}
      </div>
    </div>
    """, unsafe_allow_html=True)

    _, col_logout = st.columns([10, 1])
    with col_logout:
        if st.button("🚪 Exit"):
            for k in ["authenticated","username","role","name","session_id","active_video"]:
                st.session_state.pop(k, None)
            st.rerun()

    if st.session_state["role"] == "admin":
        admin_panel(users)
    else:
        client_view()

    # Fixed page watermark
    st.markdown(f"""
    <div class="watermark">
      NYZTrade | ****{st.session_state.get('username','')[-4:]} | {st.session_state.get('session_id','')}
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
