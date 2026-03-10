"""
NYZTrade Premium Video Streaming Platform
- Screenshot/Recording Prevention via CSS/JS overlays
- HD Video Upload & Streaming
- Token-based client access control
- Watermarking per session
"""

import streamlit as st
import os
import uuid
import hashlib
import json
import time
import base64
from pathlib import Path
from datetime import datetime, timedelta
import hmac

# ─── Page Config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NYZTrade Premium",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Constants ───────────────────────────────────────────────────────────────
VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)
USERS_FILE = Path("users.json")
SECRET_KEY = os.environ.get("SECRET_KEY", "nyztrade-secret-2024")

# ─── Anti-Capture CSS + JS ───────────────────────────────────────────────────
ANTI_CAPTURE_CSS_JS = """
<style>
  /* Disable text selection everywhere */
  * {
    -webkit-user-select: none !important;
    -moz-user-select: none !important;
    -ms-user-select: none !important;
    user-select: none !important;
  }

  /* Disable pointer events on video to block right-click save */
  video {
    pointer-events: none !important;
    -webkit-user-drag: none !important;
  }

  /* Invisible overlay blocks screenshot tools that grab DOM */
  .video-protect-wrapper {
    position: relative;
    display: inline-block;
    width: 100%;
  }

  .anti-capture-overlay {
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    z-index: 9999;
    background: transparent;
    pointer-events: none; /* allow click-through to controls below */
  }

  /* Watermark overlay */
  .watermark {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) rotate(-30deg);
    font-size: 1.8rem;
    color: rgba(255,165,0,0.12);
    font-weight: bold;
    pointer-events: none;
    z-index: 10000;
    white-space: nowrap;
    letter-spacing: 4px;
  }

  /* Block DevTools detection visual cue */
  body {
    -webkit-touch-callout: none;
  }

  /* Hide Streamlit default menu and footer */
  #MainMenu {visibility: hidden;}
  footer {visibility: hidden;}
  header {visibility: hidden;}
</style>

<script>
(function() {
  // 1. Disable right-click context menu
  document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    return false;
  });

  // 2. Block PrintScreen, F12, Ctrl+Shift+I, Ctrl+U, Ctrl+S
  document.addEventListener('keydown', function(e) {
    const blocked = [
      e.key === 'PrintScreen',
      e.key === 'F12',
      (e.ctrlKey && e.shiftKey && ['I','i','J','j','C','c'].includes(e.key)),
      (e.ctrlKey && ['u','U','s','S','p','P'].includes(e.key)),
      (e.metaKey && ['u','U','s','S','p','P'].includes(e.key)),
    ];
    if (blocked.some(Boolean)) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }
  });

  // 3. Detect visibility change (tab switch / screen capture tools)
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
      var vids = document.querySelectorAll('video');
      vids.forEach(function(v) { v.pause(); });
    }
  });

  // 4. Detect DevTools open via window size heuristic
  var devToolsCheck = function() {
    var threshold = 160;
    if (
      window.outerWidth - window.innerWidth > threshold ||
      window.outerHeight - window.innerHeight > threshold
    ) {
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0a0a0a;color:#ff4444;font-size:2rem;font-family:sans-serif;">🔒 Access Denied: Developer Tools Detected</div>';
    }
  };
  setInterval(devToolsCheck, 1500);

  // 5. Disable drag on all media
  document.addEventListener('dragstart', function(e) {
    if (e.target.tagName === 'VIDEO' || e.target.tagName === 'IMG') {
      e.preventDefault();
    }
  });
})();
</script>
"""

# ─── Helper: Load / Save Users ───────────────────────────────────────────────
def load_users():
    if USERS_FILE.exists():
        with open(USERS_FILE) as f:
            return json.load(f)
    # Default demo users
    default = {
        "admin": {
            "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
            "role": "admin",
            "name": "Admin",
            "email": "admin@nyztrade.com"
        },
        "premium1": {
            "password_hash": hashlib.sha256("premium123".encode()).hexdigest(),
            "role": "premium",
            "name": "Premium Client 1",
            "email": "client1@example.com"
        },
        "premium2": {
            "password_hash": hashlib.sha256("premium456".encode()).hexdigest(),
            "role": "premium",
            "name": "Premium Client 2",
            "email": "client2@example.com"
        },
    }
    with open(USERS_FILE, "w") as f:
        json.dump(default, f, indent=2)
    return default

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def verify_password(username, password, users):
    if username not in users:
        return False
    h = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(h, users[username]["password_hash"])

# ─── Helper: Video List ───────────────────────────────────────────────────────
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

# ─── Helper: Video to base64 for inline HTML5 player ─────────────────────────
def get_video_b64(path: Path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def render_protected_video(video_path: Path, watermark_text: str, username: str):
    """Render video with anti-capture overlay and dynamic watermark."""
    ext = video_path.suffix.lower().lstrip(".")
    mime_map = {"mp4": "video/mp4", "webm": "video/webm", "ogv": "video/ogg", "mov": "video/mp4"}
    mime = mime_map.get(ext, "video/mp4")

    # Use file URL served by Streamlit static for large files
    # For demo, embed as base64 (works for files < ~200MB reasonably)
    b64 = get_video_b64(video_path)
    src = f"data:{mime};base64,{b64}"

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""
    <div style="position:relative; width:100%;">
      <!-- Dynamic watermark -->
      <div style="
        position:absolute; top:50%; left:50%;
        transform: translate(-50%,-50%) rotate(-25deg);
        font-size:1.5rem; color:rgba(255,140,0,0.18);
        font-weight:900; pointer-events:none; z-index:500;
        white-space:nowrap; letter-spacing:3px; font-family:monospace;">
        {watermark_text} &nbsp; {ts}
      </div>

      <!-- Anti-capture transparent overlay (sits over video visually) -->
      <div style="
        position:absolute; top:0; left:0; width:100%; height:100%;
        z-index:400; background:transparent; pointer-events:none;">
      </div>

      <!-- Video player -->
      <video
        id="nyztrade-player"
        controls
        controlsList="nodownload nofullscreen noremoteplayback"
        disablePictureInPicture
        disableRemotePlayback
        style="width:100%; border-radius:8px; outline:none;"
        oncontextmenu="return false;"
      >
        <source src="{src}" type="{mime}">
        Your browser does not support HTML5 video.
      </video>
    </div>

    <script>
    (function() {{
      var player = document.getElementById('nyztrade-player');
      if (!player) return;

      // Disable download via attribute
      player.addEventListener('contextmenu', function(e) {{ e.preventDefault(); }});

      // Pause on tab/window hide
      document.addEventListener('visibilitychange', function() {{
        if (document.hidden) player.pause();
      }});

      // Blur video on PrintScreen key
      document.addEventListener('keyup', function(e) {{
        if (e.key === 'PrintScreen') {{
          player.pause();
          player.style.filter = 'blur(20px)';
          setTimeout(function() {{ player.style.filter = 'none'; }}, 3000);
        }}
      }});
    }})();
    </script>
    """
    st.components.v1.html(html, height=500, scrolling=False)

# ─── Login Screen ─────────────────────────────────────────────────────────────
def login_screen(users):
    st.markdown(ANTI_CAPTURE_CSS_JS, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        st.markdown("""
        <div style='text-align:center; padding: 2rem 0 1rem 0;'>
          <span style='font-size:2.8rem;'>🎬</span>
          <h1 style='color:#FFA500; margin:0.3rem 0; font-size:1.8rem;'>NYZTrade Premium</h1>
          <p style='color:#888; font-size:0.9rem;'>Exclusive Content for Premium Clients</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter username")
            password = st.text_input("Password", type="password", placeholder="Enter password")
            submitted = st.form_submit_button("🔐 Login", use_container_width=True)

        if submitted:
            if verify_password(username, password, users):
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
                st.session_state["role"] = users[username]["role"]
                st.session_state["name"] = users[username]["name"]
                st.session_state["session_id"] = str(uuid.uuid4())[:8].upper()
                st.rerun()
            else:
                st.error("❌ Invalid credentials. Contact support.")

        st.markdown("""
        <div style='text-align:center; margin-top:1.5rem; color:#555; font-size:0.8rem;'>
          🔒 Protected Platform &nbsp;|&nbsp; © NYZTrade Analytics Pvt. Ltd.
        </div>
        """, unsafe_allow_html=True)

# ─── Admin Panel ──────────────────────────────────────────────────────────────
def admin_panel(users):
    st.markdown("### 🛠️ Admin Panel")

    tab1, tab2, tab3 = st.tabs(["📤 Upload Video", "🎬 Manage Videos", "👥 Manage Users"])

    # ── Upload Tab ──
    with tab1:
        st.markdown("#### Upload HD Video")
        title = st.text_input("Video Title", placeholder="e.g. Options Greeks Masterclass - Module 1")
        description = st.text_area("Description", placeholder="Brief description of this video...", height=80)
        category = st.selectbox("Category", ["Options Trading", "Stock Analysis", "ESG Investing", "Technical Analysis", "Fundamental Analysis", "General"])
        thumbnail_url = st.text_input("Thumbnail URL (optional)", placeholder="https://...")

        uploaded = st.file_uploader(
            "Upload HD Video",
            type=["mp4", "webm", "mov", "mkv"],
            help="Supports MP4, WebM, MOV, MKV — HD/4K recommended"
        )

        if uploaded and title:
            if st.button("💾 Save Video", use_container_width=True, type="primary"):
                vid_id = str(uuid.uuid4())[:12]
                ext = uploaded.name.split(".")[-1].lower()
                save_path = VIDEO_DIR / f"{vid_id}.{ext}"

                with st.spinner(f"Uploading {uploaded.name} ({uploaded.size / 1024 / 1024:.1f} MB)..."):
                    with open(save_path, "wb") as f:
                        f.write(uploaded.read())

                meta = get_video_list()
                meta[vid_id] = {
                    "title": title,
                    "description": description,
                    "category": category,
                    "filename": f"{vid_id}.{ext}",
                    "size_mb": round(uploaded.size / 1024 / 1024, 2),
                    "uploaded_at": datetime.now().isoformat(),
                    "thumbnail": thumbnail_url,
                    "uploader": st.session_state["username"]
                }
                save_video_meta(meta)
                st.success(f"✅ '{title}' uploaded successfully! ({meta[vid_id]['size_mb']} MB)")
                st.balloons()

    # ── Manage Videos Tab ──
    with tab2:
        meta = get_video_list()
        if not meta:
            st.info("No videos uploaded yet.")
        else:
            for vid_id, info in meta.items():
                with st.expander(f"🎬 {info['title']} — {info['category']} ({info['size_mb']} MB)"):
                    st.write(f"**Description:** {info.get('description','N/A')}")
                    st.write(f"**Uploaded:** {info['uploaded_at'][:10]}  |  **By:** {info.get('uploader','admin')}")
                    st.write(f"**File:** `{info['filename']}`")
                    if st.button(f"🗑️ Delete", key=f"del_{vid_id}"):
                        fp = VIDEO_DIR / info["filename"]
                        if fp.exists():
                            fp.unlink()
                        del meta[vid_id]
                        save_video_meta(meta)
                        st.success("Deleted.")
                        st.rerun()

    # ── Manage Users Tab ──
    with tab3:
        st.markdown("#### Current Users")
        for uname, uinfo in users.items():
            cols = st.columns([2, 1, 1, 1])
            cols[0].write(f"**{uname}** ({uinfo.get('name','')})")
            cols[1].write(uinfo["role"])
            cols[2].write(uinfo.get("email", ""))

        st.divider()
        st.markdown("#### Add New Premium Client")
        with st.form("add_user_form"):
            new_user = st.text_input("Username")
            new_pass = st.text_input("Password", type="password")
            new_name = st.text_input("Full Name")
            new_email = st.text_input("Email")
            new_role = st.selectbox("Role", ["premium", "admin"])
            add_btn = st.form_submit_button("➕ Add User")

        if add_btn and new_user and new_pass:
            if new_user in users:
                st.error("Username already exists.")
            else:
                users[new_user] = {
                    "password_hash": hashlib.sha256(new_pass.encode()).hexdigest(),
                    "role": new_role,
                    "name": new_name,
                    "email": new_email
                }
                save_users(users)
                st.success(f"✅ User '{new_user}' added.")
                st.rerun()

# ─── Premium Client View ──────────────────────────────────────────────────────
def client_view():
    meta = get_video_list()
    username = st.session_state["username"]
    session_id = st.session_state.get("session_id", "DEMO")
    watermark = f"NYZTrade | {username.upper()} | {session_id}"

    # Category filter
    categories = list(set(v["category"] for v in meta.values())) if meta else []
    selected_cat = st.selectbox("📂 Filter by Category", ["All"] + sorted(categories))

    filtered = {k: v for k, v in meta.items()
                if selected_cat == "All" or v["category"] == selected_cat}

    if not filtered:
        st.info("🎬 No videos available yet. Check back soon!")
        return

    # Video grid
    cols = st.columns(3)
    for i, (vid_id, info) in enumerate(filtered.items()):
        with cols[i % 3]:
            thumb = info.get("thumbnail") or "https://via.placeholder.com/320x180/0a0a0a/FFA500?text=▶+NYZTrade"
            st.markdown(f"""
            <div style="border:1px solid #333; border-radius:10px; padding:0.5rem; margin-bottom:0.5rem; background:#111;">
              <img src="{thumb}" style="width:100%; border-radius:6px; height:120px; object-fit:cover;" />
              <p style="color:#FFA500; font-weight:700; margin:0.4rem 0 0.1rem; font-size:0.85rem;">{info['title']}</p>
              <p style="color:#666; font-size:0.72rem; margin:0;">{info['category']} &nbsp;|&nbsp; {info['size_mb']} MB</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("▶ Watch", key=f"watch_{vid_id}", use_container_width=True):
                st.session_state["active_video"] = vid_id

    # Video player
    if "active_video" in st.session_state:
        vid_id = st.session_state["active_video"]
        if vid_id in meta:
            info = meta[vid_id]
            video_path = VIDEO_DIR / info["filename"]
            st.divider()
            st.markdown(f"### 🎬 {info['title']}")
            st.caption(f"📁 {info['category']}  |  📅 {info['uploaded_at'][:10]}  |  📦 {info['size_mb']} MB")

            if video_path.exists():
                with st.spinner("Loading protected stream..."):
                    render_protected_video(video_path, watermark, username)
                st.markdown(f"""
                <div style="color:#444; font-size:0.7rem; text-align:center; margin-top:0.3rem;">
                  🔒 This content is watermarked and protected. Session: {session_id} &nbsp;|&nbsp; User: {username.upper()}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.error("Video file not found. Please contact support.")

# ─── Main App ─────────────────────────────────────────────────────────────────
def main():
    users = load_users()

    # Inject global anti-capture JS/CSS
    st.markdown(ANTI_CAPTURE_CSS_JS, unsafe_allow_html=True)

    # Session guard
    if not st.session_state.get("authenticated"):
        login_screen(users)
        return

    # Header
    st.markdown(f"""
    <div style="display:flex; align-items:center; justify-content:space-between;
         background:linear-gradient(90deg,#0a0a0a,#1a1a1a); padding:0.8rem 1.5rem;
         border-bottom:2px solid #FFA500; margin-bottom:1rem; border-radius:0 0 8px 8px;">
      <div>
        <span style="color:#FFA500; font-size:1.4rem; font-weight:900;">🎬 NYZTrade Premium</span>
        <span style="color:#555; font-size:0.8rem; margin-left:1rem;">Exclusive Content Platform</span>
      </div>
      <div style="color:#888; font-size:0.8rem; text-align:right;">
        👤 {st.session_state['name']} &nbsp;|&nbsp;
        <span style="color:#FFA500;">{'🛡️ ADMIN' if st.session_state['role']=='admin' else '⭐ PREMIUM'}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Logout
    col_main, col_logout = st.columns([10, 1])
    with col_logout:
        if st.button("🚪 Exit"):
            for key in ["authenticated", "username", "role", "name", "session_id", "active_video"]:
                st.session_state.pop(key, None)
            st.rerun()

    # Role-based routing
    if st.session_state["role"] == "admin":
        admin_panel(users)
    else:
        client_view()

    # Fixed watermark for logged-in users
    st.markdown(f"""
    <div class="watermark">
      NYZTrade | {st.session_state.get('username','').upper()} | {st.session_state.get('session_id','')}
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
