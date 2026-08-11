"""FastBI 3-pane layout — business intelligence with Plotly charts and an AI rail."""
from __future__ import annotations

from fasthtml.common import (
    Div, H1, H2, H3, H4, P, Span, A, Button, Form, Input, Textarea, Select, Option, Title, Link, Script, Style, NotStr,
)

LAYOUT_CSS = """
:root{
  --bg:#f4f6fb; --surface:#ffffff; --surface-2:#eef1f8; --border:#dee3ef; --text:#16203a;
  --text-dim:#48526e; --text-mute:#8590ab; --accent:#2563eb; --accent-hover:#1d4ed8;
  --accent-light:#dbe7fe; --ok:#16a34a; --warn:#d97706; --danger:#e11d48;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;height:100%;background:var(--bg);color:var(--text);
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:14px;}
a{color:var(--accent);text-decoration:none;} a:hover{text-decoration:underline;}
.app{display:grid;grid-template-columns:230px 1fr var(--rail,340px);grid-template-rows:52px 1fr;
  grid-template-areas:"top top top" "left center right";height:100vh;overflow:hidden;transition:grid-template-columns .18s ease;}
.app.no-copilot{grid-template-columns:230px 1fr;grid-template-areas:"top top" "left center";}
.app.right-expanded{--rail:clamp(420px,42vw,720px);} .app.right-collapsed{--rail:0px;} .app.right-collapsed .right-pane{display:none;}
#copilot-reopen{position:fixed;right:0;bottom:26px;display:none;align-items:center;gap:6px;cursor:pointer;z-index:60;
  background:var(--accent);color:#fff;font-size:13px;font-weight:600;padding:9px 14px;border-radius:8px 0 0 8px;box-shadow:0 2px 10px rgba(0,0,0,.18);}
.app.right-collapsed #copilot-reopen{display:inline-flex;}
.copilot-min,.copilot-exp{cursor:pointer;border:1px solid var(--border);background:var(--surface);border-radius:6px;padding:4px 9px;font-size:13px;line-height:1;color:var(--text-mute);}
.topbar{grid-area:top;display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:var(--surface);border-bottom:1px solid var(--border);}
.brand{font-weight:700;letter-spacing:.3px;display:flex;align-items:center;gap:8px;font-size:16px;}
.brand-dot{width:11px;height:11px;background:var(--accent);border-radius:3px;display:inline-block;}
.brand-wordmark{font-weight:800;color:var(--text);}
.env-pill{background:var(--accent-light);color:var(--accent-hover);padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;}
.topbar .actions{display:flex;gap:10px;align-items:center;}
.left-pane{grid-area:left;background:var(--surface);border-right:1px solid var(--border);padding:12px 0;overflow-y:auto;}
.nav-section{margin-bottom:14px;} .nav-section h4{margin:6px 16px 4px;font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--text-mute);font-weight:700;}
.nav-item{display:flex;align-items:center;gap:9px;padding:8px 16px;color:var(--text-dim);cursor:pointer;border-left:3px solid transparent;}
.nav-item:hover{background:var(--surface-2);color:var(--text);text-decoration:none;}
.nav-item.active{background:var(--accent-light);color:var(--accent-hover);border-left-color:var(--accent);font-weight:600;}
.nav-icon{width:18px;display:inline-block;text-align:center;}
.center-pane{grid-area:center;overflow-y:auto;padding:20px 24px;}
.page-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;}
.page-title h1{margin:0;font-size:22px;font-weight:700;} .page-title .sub{color:var(--text-mute);font-size:13px;margin-top:3px;}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px;}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;position:relative;overflow:hidden;}
.kpi .label{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--text-mute);font-weight:600;}
.kpi .value{font-size:24px;font-weight:700;margin-top:4px;} .kpi .trend{font-size:12px;color:var(--text-mute);margin-top:2px;}
.kpi::after{content:'';position:absolute;top:0;right:0;bottom:0;width:4px;background:var(--accent);}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-bottom:16px;}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;} .card-header h3{margin:0;font-size:15px;font-weight:700;}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
table.tbl{width:100%;border-collapse:collapse;font-size:13px;}
table.tbl th{text-align:left;padding:8px 10px;background:var(--surface-2);color:var(--text-dim);font-weight:600;border-bottom:1px solid var(--border);}
table.tbl td{padding:7px 10px;border-bottom:1px solid var(--border);} table.tbl tr:last-child td{border-bottom:0;} table.tbl tr:hover td{background:var(--surface-2);}
table.tbl td.num,table.tbl th.num{text-align:right;font-variant-numeric:tabular-nums;}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600;background:var(--surface-2);color:var(--text-dim);}
.pill.bar{background:#dbe7fe;color:#1d4ed8;} .pill.line{background:#dcfce7;color:#166534;} .pill.pie{background:#fef3c7;color:#92400e;} .pill.number{background:#ede9fe;color:#6d28d9;}
.dash-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.dash-item.full{grid-column:1 / -1;}
.dash-ctl{display:inline-flex;gap:4px;}
.dash-ctl .btn.sm{padding:2px 8px;font-size:12px;line-height:1.3;}
.plot{width:100%;height:300px;}
.btn{padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;font-size:13px;}
.btn:hover{background:var(--surface-2);} .btn.primary{background:var(--accent);color:#fff;border-color:var(--accent);} .btn.primary:hover{background:var(--accent-hover);} .btn.sm{padding:3px 9px;font-size:12px;}
.seg{display:inline-flex;gap:6px;margin-bottom:14px;flex-wrap:wrap;}
.seg a{padding:6px 12px;border:1px solid var(--border);border-radius:8px;color:var(--text-dim);background:var(--surface);font-size:13px;}
.seg a.active{background:var(--accent);color:#fff;border-color:var(--accent);}
.sqlbox{width:100%;min-height:120px;font-family:ui-monospace,SFMono-Regular,monospace;font-size:13px;border:1px solid var(--border);
  border-radius:8px;padding:12px;resize:vertical;background:#0f172a;color:#e2e8f0;line-height:1.5;}
.askbox{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px;}
.schema-table{margin-bottom:12px;} .schema-table .tn{font-weight:700;color:var(--accent-hover);font-family:ui-monospace,monospace;}
.schema-table .cols{color:var(--text-dim);font-size:12.5px;font-family:ui-monospace,monospace;margin-top:3px;}
.sql-result-err{background:#ffe4e6;border:1px solid #fecdd3;color:#9f1239;padding:10px 14px;border-radius:8px;font-size:13px;}
.code{font-family:ui-monospace,monospace;font-size:12.5px;background:var(--surface-2);padding:2px 6px;border-radius:4px;}
.login-wrap{height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#e8eefc 0%,#dbe7fe 100%);}
.login-card{background:#fff;padding:36px 40px;border-radius:14px;width:360px;box-shadow:0 20px 40px rgba(15,23,42,.08);}
.login-card h1{margin:0 0 4px;font-size:22px;} .login-card p{margin:0 0 20px;color:var(--text-mute);font-size:13px;}
.login-card input{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:10px;font-size:14px;}
.login-card button{width:100%;padding:10px;font-weight:600;} .login-card .error{color:var(--danger);font-size:12px;margin:6px 0;} .login-card .hint{font-size:11.5px;color:var(--text-mute);margin-top:10px;text-align:center;}
.right-pane{grid-area:right;background:var(--surface);border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;}
.right-header{padding:12px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;} .right-header h3{margin:0;font-size:14px;font-weight:700;} .right-header .tabs{display:flex;gap:6px;}
.chat-body{flex:1;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:12px;}
.msg{max-width:90%;padding:10px 14px;border-radius:12px;font-size:13px;line-height:1.55;overflow-wrap:anywhere;}
.msg.user{background:var(--accent);color:#fff;align-self:flex-end;border-bottom-right-radius:3px;white-space:pre-wrap;}
.msg.assistant{background:var(--surface-2);border:1px solid var(--border);color:var(--text);align-self:flex-start;border-bottom-left-radius:3px;}
.msg table{width:100%;table-layout:fixed;font-size:11.5px;border-collapse:collapse;border:1px solid var(--border);margin:6px 0;}
.msg th{background:var(--text);color:#fff;font-size:10.5px;} .msg th,.msg td{text-align:left;padding:5px 7px;border:1px solid var(--border);overflow-wrap:anywhere;}
.msg pre{background:#0f172a;color:#e2e8f0;padding:8px;border-radius:6px;font-size:12px;overflow-x:auto;white-space:pre-wrap;} .msg code{background:rgba(0,0,0,.06);padding:1px 4px;border-radius:3px;font-size:12px;}
.chat-input{border-top:1px solid var(--border);padding:10px;background:var(--surface);} .chat-input-row{display:flex;gap:8px;align-items:stretch;}
.chat-input-row input{flex:1;min-width:0;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;outline:none;}
.chat-input-row input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light);}
.chat-send-btn{display:inline-flex;align-items:center;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:0 16px;font-weight:600;font-size:13px;cursor:pointer;}
.chat-send-btn:disabled{background:var(--text-mute);cursor:not-allowed;}
.chat-mode{padding:0 8px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text-dim);font-size:12px;}
.chat-empty-hint{color:var(--text-mute);font-size:12.5px;line-height:1.5;text-align:center;padding:18px 14px;}
.sample-cards{padding:.4rem 1rem .8rem;background:var(--surface);border-top:1px solid var(--border);}
.sample-cards-label{display:inline-block;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.12em;color:var(--text-mute);margin-bottom:6px;}
.sample-card{display:flex;align-items:center;gap:8px;background:var(--bg);border:1px solid var(--border);padding:9px 12px;border-radius:10px;font-size:12.5px;cursor:pointer;color:var(--text-dim);width:100%;text-align:left;line-height:1.35;margin-bottom:6px;font-family:inherit;}
.sample-card::before{content:"💬";flex-shrink:0;} .sample-card:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-light);}
.thinking-indicator{display:flex;align-items:center;gap:8px;padding:6px 14px;font-size:12.5px;color:var(--text-mute);align-self:flex-start;}
.thinking-indicator .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);animation:pulse 1.2s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:.35;transform:scale(.85);}50%{opacity:1;transform:scale(1.1);}}
.spinner{display:inline-block;width:13px;height:13px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;}
@keyframes spin{to{transform:rotate(360deg);}}

/* Main conversational workspace */
.ai-center-pane{padding:0;overflow:hidden;}
.ai-workspace{height:100%;min-height:0;display:flex;flex-direction:column;background:var(--surface);}
.ai-workspace-header{height:58px;flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;padding:0 22px;border-bottom:1px solid var(--border);}
.ai-workspace-title{display:flex;align-items:center;gap:10px;}.ai-workspace-title h2{font-size:15px;margin:0;}.ai-status{font-size:11px;color:var(--ok);display:flex;align-items:center;gap:5px;}
.ai-status::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--ok);}
.main-chat-body{flex:1;min-height:0;overflow-y:auto;padding:28px clamp(20px,7vw,96px);display:flex;flex-direction:column;gap:18px;}
.main-chat-body .msg{width:min(760px,92%);max-width:760px;font-size:14px;}.main-chat-body .msg.assistant{background:transparent;border:0;padding:0;}
.main-chat-body .msg.assistant .msg-content{background:var(--surface-2);border:1px solid var(--border);border-radius:14px 14px 14px 4px;padding:13px 16px;}
.main-chat-body .msg.user{padding:12px 16px;border-radius:14px 14px 4px 14px;}
.assistant-label{font-size:11px;font-weight:700;color:var(--text-mute);margin:0 0 5px 3px;text-transform:uppercase;letter-spacing:.05em;}
.ai-welcome{margin:auto;max-width:720px;text-align:center;padding:40px 20px;}.ai-welcome-mark{width:58px;height:58px;margin:0 auto 18px;border-radius:18px;background:linear-gradient(145deg,var(--accent),#7c3aed);display:grid;place-items:center;color:white;font-size:27px;box-shadow:0 12px 28px rgba(37,99,235,.22);}
.ai-welcome h1{font-size:30px;margin:0 0 10px;letter-spacing:-.025em;}.ai-welcome p{font-size:15px;line-height:1.6;color:var(--text-dim);margin:0 auto;max-width:610px;}
.main-chat-composer{flex:0 0 auto;padding:12px clamp(20px,7vw,96px) 16px;border-top:1px solid var(--border);background:var(--surface);}
.composer-shell{max-width:900px;margin:0 auto;border:1px solid var(--border);border-radius:14px;background:var(--surface);box-shadow:0 5px 20px rgba(15,23,42,.06);padding:9px;}
.composer-shell textarea{width:100%;min-height:48px;max-height:180px;resize:none;overflow-y:hidden;border:0;outline:0;padding:7px 9px;font:inherit;line-height:1.5;color:var(--text);}
.composer-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;}.composer-actions-left{display:flex;align-items:center;gap:8px;}.composer-hint{font-size:11px;color:var(--text-mute);}
.main-send-btn{width:38px;height:36px;border:0;border-radius:9px;background:var(--accent);color:white;cursor:pointer;font-size:18px;}.main-send-btn:disabled{opacity:.45;cursor:not-allowed;}
.main-suggestion-bar{flex:0 0 auto;padding:0 clamp(20px,7vw,96px) 14px;background:var(--surface);}.main-suggestion-inner{max-width:900px;margin:0 auto;}.main-suggestion-label{display:block;margin:0 0 7px 2px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-mute);}
.main-samples{display:flex;gap:7px;overflow-x:auto;scrollbar-width:none;padding-bottom:1px;}.main-samples::-webkit-scrollbar{display:none;}.main-samples .sample-card{width:auto;flex:0 0 auto;margin:0;border-radius:999px;padding:8px 13px;background:var(--surface-2);}

/* Stream and generation progress */
.stream-progress{width:min(620px,92%);align-self:flex-start;border:1px solid var(--border);border-radius:12px;background:var(--surface);padding:12px 14px;box-shadow:0 4px 16px rgba(15,23,42,.05);}
.stream-progress-top{display:flex;justify-content:space-between;gap:14px;font-size:12px;color:var(--text-dim);margin-bottom:8px;}.stream-progress-label{font-weight:600;color:var(--text);}.stream-progress-time{font-variant-numeric:tabular-nums;color:var(--text-mute);}
.progress-track{height:6px;border-radius:999px;background:var(--surface-2);overflow:hidden;}.progress-fill{height:100%;width:7%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),#7c3aed);transition:width .35s ease;position:relative;}.progress-fill::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.7),transparent);animation:shimmer 1.2s linear infinite;}
@keyframes shimmer{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
.generation-progress{display:none;margin-top:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-2);padding:11px 13px;}.generation-progress.htmx-request{display:block;}.generation-progress .progress-fill{width:45%;animation:indeterminate 1.5s ease-in-out infinite;}
@keyframes indeterminate{0%{transform:translateX(-100%);width:30%}50%{width:55%}100%{transform:translateX(260%);width:30%}}
.generation-progress-copy{display:flex;justify-content:space-between;gap:12px;font-size:12px;margin-bottom:7px;}.generation-progress-copy strong{font-weight:650;}.generation-progress-copy span{color:var(--text-mute);}
.chat-visual{width:min(760px,100%);margin-top:10px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px;}.chat-visual-title{font-size:12px;font-weight:700;margin:0 0 4px;}.chat-visual-plot{width:100%;min-height:310px;}.chat-visual-network{height:380px;border-radius:8px;background:var(--surface-2);}
@media(max-width:900px){.app,.app.no-copilot{grid-template-columns:72px 1fr;}.nav-item span:last-child,.nav-section h4{display:none}.nav-item{justify-content:center;padding:10px}.left-pane{overflow:hidden}.app.right-expanded{--rail:min(72vw,520px)}.main-chat-body,.main-chat-composer,.main-suggestion-bar{padding-left:16px;padding-right:16px}.ai-welcome h1{font-size:25px}}
@media(max-width:600px){.app,.app.no-copilot{grid-template-columns:56px 1fr}.topbar{padding:0 10px}.topbar .actions>span{display:none}.topbar .actions{gap:6px}.left-pane .nav-item{padding:9px 6px}.ai-workspace-header{height:58px;padding:0 12px}.ai-workspace-title{gap:7px}.ai-workspace-title h2{font-size:14px}.ai-workspace-header>.btn{padding:6px 8px;max-width:106px;line-height:1.2}.main-chat-body{padding:18px 12px}.main-chat-composer{padding:10px 12px 8px}.main-suggestion-bar{padding:0 12px 10px}.composer-hint{display:none}.ai-welcome{padding:24px 10px}.ai-welcome h1{font-size:24px}.ai-welcome p{font-size:14px}.main-chat-body .msg{width:96%}}
"""

NAV_ITEMS = [
    ("OVERVIEW", [("home", "Home", "📊", "/"), ("ai", "AI Assistant", "🤖", "/ai")]),
    ("ANALYZE", [("dashboards", "Dashboards", "📈", "/dashboards"),
                 ("queries", "Queries & Charts", "🧩", "/queries"),
                 ("builder", "Query Builder", "🧱", "/build"),
                 ("sqllab", "SQL Lab + Ask AI", "🧠", "/sql"),
                 ("graph", "Graph Explorer", "🕸️", "/graph"),
                 ("cypher", "Cypher Lab + Ask AI", "◇", "/cypher")]),
    ("DATA", [("sources", "Data Source", "🗄️", "/sources"),
              ("integrations", "Integrations", "🔌", "/integrations"),
              ("migrations", "Migrations", "↗", "/migrations"),
              ("ontologies", "Ontologies", "◎", "/ontologies")]),
    ("HELP", [("guide", "User Guide", "📖", "/guide"),
              ("developers", "Developers", "⌘", "/developers")]),
]
SAMPLE_QUESTIONS = [
    "What's our total revenue?",
    "Which region performs best?",
    "How is revenue trending this year?",
]


def topbar(env, user_email, show_copilot=False):
    right = Div(
        Button(NotStr("&laquo; Copilot"), id="copilot-topbar-toggle", cls="btn", onclick="toggleCopilot()") if user_email and show_copilot else None,
        Span(env, cls="env-pill"),
        Span(user_email or "", style="color:var(--text-mute);font-size:12px;") if user_email else None,
        A("Logout", href="/logout", cls="btn") if user_email else None, cls="actions")
    return Div(Div(Span(cls="brand-dot"), Span("FastBI", cls="brand-wordmark"), cls="brand"),
               right, cls="topbar")


def left_pane(active):
    sections = []
    for name, items in NAV_ITEMS:
        links = [A(Span(icon, cls="nav-icon"), Span(label), href=href,
                   cls=f"nav-item {'active' if active == key else ''}") for key, label, icon, href in items]
        sections.append(Div(H4(name), *links, cls="nav-section"))
    return Div(*sections, cls="left-pane")


def _sample_cards(compact=True):
    cards = [Button(Span(q), type="button", cls="sample-card", data_question=q,
                    onclick="askChat(this)", title=q) for q in SAMPLE_QUESTIONS]
    if not compact:
        return Div(Div(Span("Try asking", cls="main-suggestion-label"), Div(*cards, cls="main-samples"),
                       cls="main-suggestion-inner"), cls="main-suggestion-bar")
    return Div(Div(Span("Try asking:", cls="sample-cards-label")), Div(*cards), cls="sample-cards")


def right_pane_chat(thread_id):
    return Div(
        Div(H3("Dashboard copilot"),
            Div(Button("New", cls="btn", hx_get="/chat/new", hx_target="#chat-body", hx_swap="innerHTML"),
                Button(NotStr("&laquo;"), id="copilot-exp-btn", cls="copilot-exp", onclick="toggleExpand()"),
                Button(NotStr("&rsaquo;"), cls="copilot-min", onclick="toggleCopilot()"), cls="tabs"),
            cls="right-header"),
        Div(Div(P("Ask a question about the dashboard or its underlying data.",
                  cls="chat-empty-hint"), id="chat-body", data_role="messages", cls="chat-body"),
            Form(Input(type="hidden", name="thread_id", value=thread_id, id="thread-id"),
                 Div(Select(Option("Auto", value="auto", selected=True), Option("SQL", value="sql"),
                            Option("Graph", value="graph"), name="query_mode", cls="chat-mode", data_role="mode",
                            title="Choose automatic, relational, or graph execution"),
                     Input(type="text", name="message", data_role="input",
                           placeholder="Ask about your data or /metrics /help …", autocomplete="off"),
                     Button("Send", type="submit", cls="chat-send-btn", data_role="send"), cls="chat-input-row"),
                 onsubmit="return streamChat(event)", cls="chat-input"),
            _sample_cards(),
            style="display:flex;flex-direction:column;flex:1;overflow:hidden;"),
        data_chat_root="copilot", cls="right-pane")


def main_chat(thread_id, messages=()):
    history = []
    for item in messages:
        role = "user" if item.get("role") == "user" else "assistant"
        if role == "assistant":
            history.append(Div(Div("FastBI", cls="assistant-label"),
                               Div(data_markdown=item.get("content", ""), cls="msg-content"), cls="msg assistant"))
        else:
            history.append(Div(item.get("content", ""), cls="msg user"))
    welcome = None if history else Div(
        Div("✦", cls="ai-welcome-mark"), H1("Ask your data anything"),
        P("FastBI routes each question to governed SQL, your graph ontology, or the general assistant, then streams the answer and visual evidence as it is created."),
        cls="ai-welcome", data_role="welcome")
    return Div(
        Div(Div(Span(cls="brand-dot"), H2("AI Assistant"), Span("Live", cls="ai-status"), cls="ai-workspace-title"),
            Button("New conversation", cls="btn", type="button", onclick="newChat(this)"), cls="ai-workspace-header"),
        Div(welcome, *history, data_role="messages", cls="main-chat-body"),
        Form(
            Input(type="hidden", name="thread_id", value=thread_id, data_role="thread"),
            Div(Textarea(name="message", data_role="input", rows="1", autocomplete="off",
                         placeholder="Ask a question, describe a chart, or explore relationships…",
                         onkeydown="chatKeydown(event)", oninput="resizeChatInput(this)"),
                Div(Div(Select(Option("Auto route", value="auto", selected=True), Option("SQL", value="sql"),
                               Option("Graph", value="graph"), name="query_mode", data_role="mode", cls="chat-mode"),
                            Span("Enter to send · Shift+Enter for a new line", cls="composer-hint"), cls="composer-actions-left"),
                    Button("↑", type="submit", cls="main-send-btn", data_role="send", title="Send"), cls="composer-actions"),
                cls="composer-shell"),
            onsubmit="return streamChat(event)", cls="main-chat-composer"),
        _sample_cards(compact=False),
        data_chat_root="main", cls="ai-workspace")


def page(active, env, user_email, thread_id, *content, right_override=None):
    show_copilot = active == "dashboards"
    right = right_override if right_override is not None else (right_pane_chat(thread_id) if show_copilot else None)
    graph_library = (Script(src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js")
                     if active in {"graph", "cypher", "ai"} else None)
    return (Title("FastBI"),
            Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
            Script(src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"),
            Script(src="https://cdn.plot.ly/plotly-2.35.2.min.js"),
            graph_library,
            Style(LAYOUT_CSS),
            Div(topbar(env, user_email, show_copilot), left_pane(active),
                Div(*content, cls=f"center-pane {'ai-center-pane' if active == 'ai' else ''}"), right,
                Div(NotStr("&lsaquo; Dashboard copilot"), id="copilot-reopen", onclick="toggleCopilot()") if show_copilot else None,
                cls=f"app {'with-copilot' if show_copilot else 'no-copilot'}"),
            Script(LAYOUT_JS))


def kpi_card(label, value, trend=""):
    return Div(Div(label, cls="label"), Div(str(value), cls="value"),
               Div(trend, cls="trend") if trend else None, cls="kpi")


def generation_progress(element_id, label, detail="This can take a little while."):
    """HTMX indicator used by non-streaming AI generation forms."""
    return Div(
        Div(Span(label), Span(detail), cls="generation-progress-copy"),
        Div(Div(cls="progress-fill"), cls="progress-track"),
        id=element_id, cls="generation-progress htmx-indicator",
    )


LAYOUT_JS = """
function _sync(){var app=document.querySelector('.app');if(!app)return;
  var ex=app.classList.contains('right-expanded'),col=app.classList.contains('right-collapsed');
  var eb=document.getElementById('copilot-exp-btn');if(eb){eb.innerHTML=ex?'\\u00BB':'\\u00AB';}
  var tb=document.getElementById('copilot-topbar-toggle');if(tb){tb.innerHTML=col?'\\u00AB Copilot':'Copilot \\u203A';}}
function toggleCopilot(){var app=document.querySelector('.app');if(!app)return;app.classList.toggle('right-collapsed');
  if(app.classList.contains('right-collapsed'))app.classList.remove('right-expanded');
  try{localStorage.setItem('fiCollapsed',app.classList.contains('right-collapsed')?'1':'0');}catch(e){}_sync();}
function toggleExpand(){var app=document.querySelector('.app');if(!app)return;app.classList.remove('right-collapsed');app.classList.toggle('right-expanded');
  try{localStorage.setItem('fiExpanded',app.classList.contains('right-expanded')?'1':'0');localStorage.setItem('fiCollapsed','0');}catch(e){}_sync();}
(function(){try{var app=document.querySelector('.app');if(!app)return;
  if(localStorage.getItem('fiCollapsed')==='1')app.classList.add('right-collapsed');
  else if(localStorage.getItem('fiExpanded')==='1')app.classList.add('right-expanded');}catch(e){}})();
document.addEventListener('DOMContentLoaded',_sync);
function _esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function _md(t){try{return marked.parse(t);}catch(e){return _esc(t);}}
function _parts(root){return {messages:root.querySelector('[data-role="messages"]'),input:root.querySelector('[data-role="input"]'),
  mode:root.querySelector('[data-role="mode"]'),thread:root.querySelector('[data-role="thread"],input[name="thread_id"]'),send:root.querySelector('[data-role="send"]')};}
function _scroll(root){var p=_parts(root),cb=p.messages;if(cb)cb.scrollTop=cb.scrollHeight;}
function addBubble(root,role,html){var p=_parts(root),cb=p.messages;if(!cb)return null;
  var h=cb.querySelector('.chat-empty-hint,[data-role="welcome"]');if(h)h.remove();
  var d=document.createElement('div');d.className='msg '+role;
  if(role==='assistant')d.innerHTML='<div class="assistant-label">FastBI</div><div class="msg-content">'+(html||'')+'</div>';
  else d.innerHTML=html||'';cb.appendChild(d);_scroll(root);return d;}
function showProgress(root){var cb=_parts(root).messages;if(!cb)return null;var d=document.createElement('div');d.className='stream-progress';
  d.innerHTML='<div class="stream-progress-top"><span class="stream-progress-label">Understanding your question…</span><span class="stream-progress-time">0s</span></div><div class="progress-track"><div class="progress-fill"></div></div>';
  cb.appendChild(d);var started=Date.now(),timer=setInterval(function(){var t=d.querySelector('.stream-progress-time');if(t)t.textContent=Math.floor((Date.now()-started)/1000)+'s';},1000);
  root._fastbiProgress={el:d,timer:timer};_scroll(root);return d;}
function updateProgress(root,payload){var state=root._fastbiProgress;if(!state)return;var label=state.el.querySelector('.stream-progress-label'),fill=state.el.querySelector('.progress-fill');
  if(label&&payload.label)label.textContent=payload.label;if(fill&&payload.percent!=null)fill.style.width=Math.max(4,Math.min(100,payload.percent))+'%';_scroll(root);}
function hideProgress(root){var state=root._fastbiProgress;if(!state)return;clearInterval(state.timer);if(state.el&&state.el.parentNode)state.el.parentNode.removeChild(state.el);root._fastbiProgress=null;}
function parseSSE(raw){var type='message',data=[];raw.split(/\\r?\\n/).forEach(function(line){if(line.indexOf('event:')===0)type=line.slice(6).trim();else if(line.indexOf('data:')===0)data.push(line.slice(5).trimStart());});
  var payload={};try{payload=JSON.parse(data.join('\\n')||'{}');}catch(e){};if(type==='message')type=payload.type||(payload.token?'token':payload.error?'error':payload.done?'done':'message');return {type:type,payload:payload};}
function renderVisual(root,payload,bubble){if(!payload)return;var host=bubble?bubble.querySelector('.msg-content'):null;if(!host){bubble=addBubble(root,'assistant','');host=bubble.querySelector('.msg-content');}
  var card=document.createElement('div');card.className='chat-visual';var title=document.createElement('div');title.className='chat-visual-title';title.textContent=payload.title||'Generated visual';card.appendChild(title);
  var plot=document.createElement('div');card.appendChild(plot);host.appendChild(card);
  if(payload.kind==='network'){plot.className='chat-visual-network';if(window.vis)new vis.Network(plot,{nodes:new vis.DataSet(payload.nodes||[]),edges:new vis.DataSet(payload.edges||[])},{interaction:{hover:true},physics:{stabilization:{iterations:120}},nodes:{shape:'dot',size:18,font:{size:12}},edges:{arrows:'to',smooth:{type:'dynamic'}}});}
  else{plot.className='chat-visual-plot';if(window.Plotly&&payload.figure)Plotly.newPlot(plot,payload.figure.data||[],payload.figure.layout||{},{responsive:true,displayModeBar:false});}_scroll(root);}
function askChat(btn){var root=btn.closest('[data-chat-root]');if(!root)return;var p=_parts(root);p.input.value=btn.getAttribute('data-question')||'';p.input.focus();root.querySelector('form').requestSubmit();}
function chatKeydown(ev){if(ev.key==='Enter'&&!ev.shiftKey){ev.preventDefault();ev.target.closest('form').requestSubmit();}}
function resizeChatInput(el){if(!el)return;el.style.height='auto';el.style.overflowY='hidden';el.style.height=Math.min(el.scrollHeight,180)+'px';if(el.scrollHeight>180)el.style.overflowY='auto';}
async function streamChat(ev){if(ev&&ev.preventDefault)ev.preventDefault();
  var form=ev&&ev.currentTarget?ev.currentTarget:null,root=form?form.closest('[data-chat-root]'):document.querySelector('[data-chat-root]');if(!root||root.dataset.streaming==='1')return false;
  var parts=_parts(root),input=parts.input,msg=input?input.value.trim():'';if(!msg)return false;
  root.dataset.streaming='1';if(parts.send)parts.send.disabled=true;addBubble(root,'user',_esc(msg));input.value='';resizeChatInput(input);
  var tid=parts.thread?parts.thread.value:'',bubble=null,acc='';showProgress(root);var mode=parts.mode?parts.mode.value:'auto';
  try{var resp=await fetch('/chat/stream',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({message:msg,thread_id:tid,query_mode:mode})});
    if(!resp.ok){hideProgress(root);addBubble(root,'assistant','Error: '+resp.status);root.dataset.streaming='0';if(parts.send)parts.send.disabled=false;return false;}
    var reader=resp.body.getReader(),dec=new TextDecoder(),buf='';
    while(true){var r=await reader.read();if(r.done)break;buf+=dec.decode(r.value,{stream:true});
      var idx;while((idx=buf.indexOf('\\n\\n'))!==-1){var raw=buf.slice(0,idx);buf=buf.slice(idx+2);
        var event=parseSSE(raw),p=event.payload;
        if(event.type==='progress')updateProgress(root,p);
        else if(event.type==='token'){if(acc===''){hideProgress(root);bubble=addBubble(root,'assistant','');}acc+=p.token||p.text||'';bubble.querySelector('.msg-content').innerHTML=_md(acc);_scroll(root);}
        else if(event.type==='visual'){hideProgress(root);renderVisual(root,p,bubble);}
        else if(event.type==='error'){hideProgress(root);addBubble(root,'assistant','⚠ '+_esc(p.message||p.error||'Generation failed.'));}
        else if(event.type==='done')updateProgress(root,{label:'Complete',percent:100});}}
  }catch(e){hideProgress(root);addBubble(root,'assistant','⚠ '+_esc(String(e)));}
  hideProgress(root);root.dataset.streaming='0';if(parts.send)parts.send.disabled=false;if(input)input.focus();return false;}
async function newChat(btn){var root=btn.closest('[data-chat-root]'),parts=_parts(root);if(!root)return;try{var resp=await fetch('/chat/new?format=json'),data=await resp.json();if(parts.thread)parts.thread.value=data.thread_id;
  parts.messages.innerHTML='<div class="ai-welcome" data-role="welcome"><div class="ai-welcome-mark">✦</div><h1>Ask your data anything</h1><p>FastBI routes each question to governed SQL, your graph ontology, or the general assistant, then streams the answer and visual evidence as it is created.</p></div>';if(parts.input)parts.input.focus();}catch(e){}}
document.addEventListener('DOMContentLoaded',function(){document.querySelectorAll('[data-markdown]').forEach(function(el){el.innerHTML=_md(el.getAttribute('data-markdown')||'');});document.querySelectorAll('.composer-shell textarea').forEach(resizeChatInput);});
document.body.addEventListener('htmx:afterSwap',function(ev){
  var root=(ev.detail&&ev.detail.target)||document;
  root.querySelectorAll('script[data-plot]').forEach(function(s){try{eval(s.textContent);}catch(e){}});
  root.querySelectorAll('script[data-network]').forEach(function(s){try{eval(s.textContent);}catch(e){console.error('Graph render failed',e);}});});
"""
