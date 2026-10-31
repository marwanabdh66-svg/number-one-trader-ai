import os
import sqlite3
from datetime import datetime
import pandas as pd
import streamlit as st
from engine import ASSETS, TIMEFRAMES, analyze_asset, fetch_market_data, get_market_assets, calculate_indicators

st.set_page_config(page_title="NUMBER ONE TRADER AI", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
DB_PATH = os.getenv("TRADER_DB_PATH", "number_one_trader.db")

def db():
    con=sqlite3.connect(DB_PATH,timeout=20); con.row_factory=sqlite3.Row; return con

def init_db():
    con=db()
    con.execute("""CREATE TABLE IF NOT EXISTS signal_history(id INTEGER PRIMARY KEY AUTOINCREMENT,asset TEXT,symbol TEXT,market TEXT,timeframe TEXT,direction TEXT,signal_type TEXT,confidence INTEGER,entry REAL,stop_loss REAL,take_profit REAL,source TEXT,created_at TEXT,reasons TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS paper_trades(id INTEGER PRIMARY KEY AUTOINCREMENT,asset TEXT,symbol TEXT,direction TEXT,timeframe TEXT,entry REAL,amount REAL,stop_loss REAL,take_profit REAL,status TEXT DEFAULT 'مفتوحة',result REAL DEFAULT 0,created_at TEXT)""")
    con.commit(); con.close()
init_db()

def save_signal(s):
    con=db()
    con.execute("""INSERT INTO signal_history(asset,symbol,market,timeframe,direction,signal_type,confidence,entry,stop_loss,take_profit,source,created_at,reasons) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(s["asset"],s["symbol"],s["market"],s["timeframe"],s["direction"],s["signal_type"],s["confidence"],s["entry"],s["stop_loss"],s["take_profit"],s["source"],s["created_at"],s["reasons"]))
    con.commit(); con.close()

@st.cache_data(ttl=60,show_spinner=False)
def cached_analysis(asset,symbol,market,timeframe,signal_filter):
    return analyze_asset(asset,symbol,market,timeframe,signal_filter)
@st.cache_data(ttl=60,show_spinner=False)
def cached_candles(symbol,timeframe):
    return fetch_market_data(symbol,timeframe)

def money(v):
    return f"{v:,.5f}" if abs(v)<100 else f"{v:,.2f}"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800;900&display=swap');
html,body,[class*="css"]{font-family:'Cairo',sans-serif}
.stApp{background:radial-gradient(ellipse at 85% -10%,#18365b 0%,transparent 38%),linear-gradient(135deg,#070b13,#0b1423 55%,#101b2e);color:#f5f7fb}
section[data-testid="stSidebar"],[data-testid="stSidebar"],button[kind="header"]{display:none!important}
.block-container{max-width:1740px;padding:1.6rem 3rem 3rem}
.brand{display:flex;align-items:center;gap:18px;padding:22px 28px;margin-bottom:18px;border:1px solid rgba(215,180,93,.55);border-radius:22px;background:linear-gradient(110deg,rgba(23,43,69,.98),rgba(8,15,28,.98));box-shadow:0 16px 42px #0005}
.brand-icon{font-size:42px}.brand-title{font-size:28px;font-weight:900;letter-spacing:1.6px;color:#e8c56c}.brand-sub{color:#aebed4;font-size:12px}.brand-live{margin-right:auto;color:#74d6a2;font-size:13px}
div[role="radiogroup"]{display:grid!important;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;padding:12px;border:1px solid #293e5b;border-radius:18px;background:#0c1728;margin:12px 0 26px}
div[role="radiogroup"] label{justify-content:center;background:#15243a;border:1px solid #2b405e;border-radius:12px;padding:10px 12px;min-height:48px}
div[role="radiogroup"] label:hover{border-color:#d7b45d;background:#203651}
div[role="radiogroup"] label p{font-size:13px;font-weight:700;color:#edf2fa}
.panel{background:linear-gradient(145deg,rgba(24,39,61,.96),rgba(12,21,36,.98));border:1px solid #2d4260;border-radius:18px;padding:22px;margin-bottom:16px;box-shadow:0 12px 30px #0002}
.kicker{color:#d8b968;font-size:12px;font-weight:800;letter-spacing:1px}.metric{font-size:28px;font-weight:900;color:#f1d27d}.muted{color:#a9b8cc;font-size:13px}
.signal-up{color:#6ee0a2;font-weight:900}.signal-down{color:#ff8c91;font-weight:900}
div.stButton>button,.stDownloadButton>button,div[data-testid="stFormSubmitButton"]>button{background:linear-gradient(135deg,#e8c56c,#b78b39);color:#101722;font-weight:900;border:0;border-radius:12px;min-height:46px}
div.stButton>button:hover{background:#ffe29a;color:#101722}
.stTextInput input,.stTextArea textarea,div[data-baseweb="select"]>div{background:#101d30;color:#fff;border:1px solid #344a68;border-radius:10px}
[data-testid="stMetric"]{background:#14243a;border:1px solid #304765;border-radius:15px;padding:16px}
[data-testid="stDataFrame"]{border:1px solid #2e4563;border-radius:13px;overflow:hidden}
hr{border-color:#2c405c}
@media(max-width:1100px){.block-container{padding:1rem}div[role="radiogroup"]{display:flex!important;overflow-x:auto;flex-wrap:nowrap}div[role="radiogroup"] label{flex:0 0 auto}}
@media(max-width:640px){.brand{padding:14px}.brand-title{font-size:19px}.brand-icon{font-size:27px}.brand-live{display:none}}
</style>
""",unsafe_allow_html=True)

st.markdown("""<div class="brand"><div class="brand-icon">📈</div><div><div class="brand-title">NUMBER ONE TRADER AI</div><div class="brand-sub">منصة تحليل الأسواق وإشارات التداول التجريبية</div></div><div class="brand-live">● النظام جاهز للتحليل</div></div>""",unsafe_allow_html=True)
pages=["🏠 الرئيسية","📡 الإشارات","🔎 التحليل","📊 الأسواق","🧪 التداول التجريبي","🗂️ سجل الإشارات","🤖 بوت تيليجرام","⚙️ الإعدادات","👑 المالك"]
page=st.radio("القائمة الرئيسية",pages,horizontal=True,label_visibility="collapsed",key="trader_nav")
defaults={"timeframe":"5 دقائق","signal_filter":"جميع الإشارات","markets":list(ASSETS.keys()),"selected_assets":[]}
for k,v in defaults.items():
    if k not in st.session_state: st.session_state[k]=v

def scan(timeframe=None,signal_filter=None,markets=None,selected=None,limit=18):
    timeframe=timeframe or st.session_state["timeframe"]; signal_filter=signal_filter or st.session_state["signal_filter"]
    markets=markets or st.session_state["markets"]; selected=selected if selected is not None else st.session_state["selected_assets"]
    assets=get_market_assets(markets,selected if selected else None); results=[]
    for asset,symbol,market in assets[:limit]:
        try:
            item=cached_analysis(asset,symbol,market,timeframe,signal_filter)
            if item: results.append(item)
        except Exception: continue
    return sorted(results,key=lambda x:x["confidence"],reverse=True)

def render_signal(s):
    cls="signal-up" if s["direction"]=="صعود" else "signal-down"; arrow="▲" if s["direction"]=="صعود" else "▼"
    st.markdown(f"""<div class="panel"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><div><div class="kicker">{s['market']} · {s['timeframe']}</div><h3 style="margin:4px 0">{s['asset']} <span class="muted">{s['symbol']}</span></h3></div><div class="{cls}" style="font-size:22px">{arrow} {s['direction']}</div></div><div style="display:flex;gap:28px;flex-wrap:wrap;margin:14px 0"><div><div class="muted">قوة الإشارة</div><b>{s['confidence']}%</b></div><div><div class="muted">سعر الدخول</div><b>{money(s['entry'])}</b></div><div><div class="muted">وقف الخسارة</div><b>{money(s['stop_loss'])}</b></div><div><div class="muted">الهدف</div><b>{money(s['take_profit'])}</b></div><div><div class="muted">RSI</div><b>{s['rsi']}</b></div></div><div class="muted">نوع الإشارة: {s['signal_type']} · مصدر البيانات: {s['source']}</div><div class="muted">الأسباب: {s['reasons']}</div></div>""",unsafe_allow_html=True)

if page=="🏠 الرئيسية":
    st.markdown("## لوحة متابعة الأسواق"); st.caption("تحليل فني آلي متعدد المؤشرات — لا ينفذ صفقات حقيقية.")
    con=db(); total=con.execute("SELECT COUNT(*) n FROM signal_history").fetchone()["n"]; trades=con.execute("SELECT COUNT(*) n FROM paper_trades").fetchone()["n"]; opened=con.execute("SELECT COUNT(*) n FROM paper_trades WHERE status='مفتوحة'").fetchone()["n"]; con.close()
    a,b,c,d=st.columns(4);a.metric("الإشارات المحفوظة",total);b.metric("الصفقات التجريبية",trades);c.metric("الصفقات المفتوحة",opened);d.metric("الأسواق المتاحة",len(ASSETS))
    l,r=st.columns([3,1])
    with l: st.markdown('<div class="panel"><div class="kicker">محرك التحليل</div><h3>اكتشف فرص السوق عبر المؤشرات الفنية</h3><p class="muted">RSI · MACD · EMA · Bollinger Bands · Stochastic · ATR</p><p class="muted">لا يصدر المحرك إشارة عند ضعف البيانات أو تضارب المؤشرات.</p></div>',unsafe_allow_html=True)
    with r: st.markdown('<div class="panel"><div class="kicker">الوضع</div><div class="metric">تجريبي</div><p class="muted">تداول افتراضي فقط</p></div>',unsafe_allow_html=True)
    if st.button("🔍 فحص الأسواق الآن",use_container_width=True):
        with st.spinner("يجري فحص الأصول وجلب البيانات..."): found=scan(limit=18)
        for s in found: save_signal(s)
        st.session_state["last_scan"]=found; st.success(f"انتهى الفحص. تم العثور على {len(found)} إشارة مطابقة.")
    for s in st.session_state.get("last_scan",[])[:6]: render_signal(s)

elif page=="📡 الإشارات":
    st.markdown("## مركز الإشارات")
    x,y,z=st.columns(3)
    with x: tf=st.selectbox("الفاصل الزمني",list(TIMEFRAMES),index=list(TIMEFRAMES).index(st.session_state["timeframe"]))
    with y: sf=st.selectbox("نوع الإشارات",["جميع الإشارات","الإشارات القوية فقط","إشارات الاتجاه","إشارات الانعكاس"])
    with z: mc=st.selectbox("نطاق الأسواق",["كل الأسواق"]+list(ASSETS.keys()))
    chosen=list(ASSETS.keys()) if mc=="كل الأسواق" else [mc]
    if st.button("تحديث الإشارات",use_container_width=True):
        with st.spinner("تحليل البيانات المتاحة..."): found=scan(tf,sf,chosen,limit=18)
        for s in found: save_signal(s)
        st.session_state["last_scan"]=found; st.success(f"تم العثور على {len(found)} إشارة.")
    signals=st.session_state.get("last_scan",[])
    if signals:
        for s in signals: render_signal(s)
    else: st.info("اضغط تحديث الإشارات لبدء الفحص.")

elif page=="🔎 التحليل":
    st.markdown("## التحليل الفني لأصل محدد")
    market=st.selectbox("اختر السوق",list(ASSETS.keys())); asset=st.selectbox("اختر الأصل",list(ASSETS[market].keys())); timeframe=st.selectbox("الفاصل الزمني",list(TIMEFRAMES),index=1)
    if st.button("تنفيذ التحليل",use_container_width=True):
        symbol=ASSETS[market][asset]
        with st.spinner("تحميل الشموع وحساب المؤشرات..."): frame,source=cached_candles(symbol,timeframe); indicators=calculate_indicators(frame)
        if indicators.empty: st.error("تعذر الحصول على بيانات كافية. قد لا يدعم مزود البيانات هذا السوق.")
        else:
            last=indicators.iloc[-1]; a,b,c,d=st.columns(4);a.metric("آخر سعر",money(float(last["close"])));b.metric("RSI",f"{last['rsi']:.2f}");c.metric("MACD","إيجابي" if last["macd"]>last["macd_signal"] else "سلبي");d.metric("الاتجاه","صاعد" if last["ema9"]>last["ema21"] else "هابط")
            st.line_chart(indicators[["close","ema9","ema21","ema50"]].tail(120),use_container_width=True); st.caption(f"مصدر البيانات: {source} · قراءة تحليلية وليست ضمانًا.")
            result=analyze_asset(asset,symbol,market,timeframe,"جميع الإشارات")
            if result:
                render_signal(result)
                if st.button("حفظ هذه الإشارة"): save_signal(result); st.success("تم حفظ الإشارة.")
            else: st.warning("لا يوجد توافق كافٍ لإصدار إشارة الآن.")

elif page=="📊 الأسواق":
    st.markdown("## الأسواق والأصول")
    for market,assets in ASSETS.items():
        with st.expander(f"{market} · {len(assets)} أصول",expanded=True): st.write(" · ".join(assets.keys()))
    st.info("المصادر المجانية: Binance للعملات الرقمية وYahoo Finance لبقية الأصول. قد لا تتوفر جميع الأصول والفواصل، وبيانات OTC غير مضمونة.")

elif page=="🧪 التداول التجريبي":
    st.markdown("## محاكي التداول التجريبي"); st.warning("محاكاة بأموال افتراضية فقط. لا تُرسل أوامر إلى وسيط.")
    con=db(); opened=con.execute("SELECT * FROM paper_trades WHERE status='مفتوحة' ORDER BY id DESC").fetchall(); closed=con.execute("SELECT * FROM paper_trades WHERE status!='مفتوحة' ORDER BY id DESC").fetchall(); con.close()
    latest=st.session_state.get("last_scan",[])
    if latest:
        labels=[f"{s['asset']} — {s['direction']} — {s['timeframe']}" for s in latest]; selected=st.selectbox("اختر إشارة",labels); signal=latest[labels.index(selected)]; amount=st.number_input("حجم الصفقة الافتراضية بالدولار",min_value=1.0,value=100.0,step=10.0)
        if st.button("فتح صفقة تجريبية",use_container_width=True):
            con=db();con.execute("INSERT INTO paper_trades(asset,symbol,direction,timeframe,entry,amount,stop_loss,take_profit,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(signal["asset"],signal["symbol"],signal["direction"],signal["timeframe"],signal["entry"],amount,signal["stop_loss"],signal["take_profit"],datetime.now().isoformat(timespec="minutes")));con.commit();con.close();st.success("تم فتح الصفقة التجريبية.")
    else: st.info("افحص الأسواق أولًا لعرض إشارات قابلة للمحاكاة.")
    st.markdown("### الصفقات المفتوحة")
    if opened:
        for row in opened:
            st.markdown(f'<div class="panel"><b>{row["asset"]} · {row["direction"]}</b><p class="muted">دخول: {money(row["entry"])} · الحجم الافتراضي: USD {row["amount"]:.2f}</p></div>',unsafe_allow_html=True)
            with st.form(f"close_trade_{row['id']}"):
                exit_price=st.number_input("سعر الإغلاق الافتراضي",min_value=0.000001,value=float(row["entry"]),format="%.6f",key=f"exit_{row['id']}"); submit=st.form_submit_button("إغلاق الصفقة")
            if submit:
                raw=(exit_price-float(row["entry"]))*float(row["amount"])/float(row["entry"]); pnl=raw if row["direction"]=="صعود" else -raw
                con=db();con.execute("UPDATE paper_trades SET status='مغلقة',result=? WHERE id=?",(pnl,row["id"]));con.commit();con.close();st.success(f"نتيجة المحاكاة: USD {pnl:.2f}");st.rerun()
    else: st.caption("لا توجد صفقات مفتوحة.")
    st.markdown("### الصفقات المغلقة")
    if closed: st.dataframe([dict(r) for r in closed],use_container_width=True,hide_index=True)
    else: st.caption("لا توجد صفقات مغلقة.")

elif page=="🗂️ سجل الإشارات":
    st.markdown("## سجل الإشارات");con=db();rows=con.execute("SELECT * FROM signal_history ORDER BY id DESC LIMIT 300").fetchall();con.close()
    if rows:
        frame=pd.DataFrame([dict(r) for r in rows]);st.dataframe(frame,use_container_width=True,hide_index=True);st.download_button("تنزيل السجل CSV",frame.to_csv(index=False).encode("utf-8-sig"),"trader_signals.csv","text/csv")
    else: st.info("سيظهر السجل بعد إجراء عمليات الفحص.")

elif page=="🤖 بوت تيليجرام":
    st.markdown("## بوت NUMBER ONE TRADER AI")
    st.markdown('<div class="panel"><div class="kicker">بوت تيليجرام</div><h3>@NumberOneTraderAI_bot</h3><p class="muted">https://t.me/NumberOneTraderAI_bot</p></div>',unsafe_allow_html=True)
    token_ready=bool(os.getenv("TELEGRAM_BOT_TOKEN") or st.secrets.get("TELEGRAM_BOT_TOKEN",""))
    st.metric("رمز ربط البوت", "موجود" if token_ready else "يحتاج إعدادًا")
    st.info("ملف تشغيل البوت موجود ضمن المشروع. يحتاج الرمز السري في إعدادات الاستضافة وتشغيل عامل مستقل.")
    st.code("/start\n/markets\n/analyze BTCUSDT 5m\n/signals\n/history\n/demo\n/settings\n/help",language="text")
    st.write("يعرض الأسواق ويحلل الأصول ويقدم آخر قراءة فنية. المحاكاة متاحة في الموقع.")

elif page=="⚙️ الإعدادات":
    st.markdown("## إعدادات التحليل")
    st.session_state["timeframe"]=st.selectbox("الفاصل الافتراضي",list(TIMEFRAMES),index=list(TIMEFRAMES).index(st.session_state["timeframe"]))
    filters=["جميع الإشارات","الإشارات القوية فقط","إشارات الاتجاه","إشارات الانعكاس"]
    st.session_state["signal_filter"]=st.selectbox("نوع الإشارات",filters,index=filters.index(st.session_state["signal_filter"]))
    st.session_state["markets"]=st.multiselect("الأسواق",list(ASSETS.keys()),default=st.session_state["markets"])
    all_assets=[asset for market in ASSETS.values() for asset in market]
    st.session_state["selected_assets"]=st.multiselect("أصول محددة (اتركها فارغة لفحص الكل)",all_assets,default=st.session_state["selected_assets"])
    st.success("تم تطبيق الإعدادات على الجلسة الحالية.")
    st.caption("SQLite محلية؛ قد لا تبقى البيانات بعد إعادة تشغيل استضافة مجانية مؤقتة.")

elif page=="👑 المالك":
    st.markdown("## لوحة المالك"); password=os.getenv("OWNER_PASSWORD") or st.secrets.get("OWNER_PASSWORD","")
    if not password: st.warning("أضف OWNER_PASSWORD إلى أسرار الاستضافة لحماية لوحة المالك.")
    else:
        entered=st.text_input("كلمة مرور المالك",type="password")
        if st.button("دخول لوحة المالك"): st.session_state["owner_access"]=(entered==password)
        if st.session_state.get("owner_access"):
            con=db(); n=con.execute("SELECT COUNT(*) n FROM signal_history").fetchone()["n"]; t=con.execute("SELECT COUNT(*) n FROM paper_trades").fetchone()["n"]; pnl=con.execute("SELECT COALESCE(SUM(result),0) n FROM paper_trades").fetchone()["n"];con.close()
            a,b,c=st.columns(3);a.metric("الإشارات",n);b.metric("الصفقات التجريبية",t);c.metric("نتيجة المحاكاة",f"USD {pnl:.2f}")
            st.info("إدارة المستخدمين والاشتراكات ومفاتيح البيانات تحتاج قاعدة بيانات دائمة وخدمات خلفية غير مفعلة في هذا الإصدار.")

st.markdown("---")
st.markdown('<div style="text-align:center;color:#899bb4;padding:10px"><b style="color:#d8b968">NUMBER ONE TRADER AI</b><br>التحليل الفني لا يضمن الأرباح. التداول ينطوي على مخاطر خسارة رأس المال.</div>',unsafe_allow_html=True)
