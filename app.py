import streamlit as st
import requests
import pandas as pd
import numpy_financial as npf

# --- PAGE CONFIG ---
st.set_page_config(page_title="DCF Master", layout="wide")

# --- API SETUP ---
# This pulls the key from Streamlit's secure storage
try:
    API_KEY = st.secrets["FMP_API_KEY"]
except FileNotFoundError:
    st.error("API Key not found. Please set FMP_API_KEY in secrets.")
    st.stop()

# --- 1. DATA FETCHING ---
def get_company_data(ticker):
    # 1. TEST THE KEY FIRST
    if not API_KEY:
        st.error("CRITICAL ERROR: API_KEY is empty. Check your secrets.toml file.")
        return None

    try:
        # 2. DEBUG MODE: Print the URL (masked) to ensure it looks right
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={API_KEY}"
        # st.write(f"Testing URL: {url.replace(API_KEY, 'HIDDEN_KEY')}") # Uncomment to see the URL structure
        
        profile_req = requests.get(url)
        
        # 3. CATCH HTTP ERRORS (401, 403, 404)
        if profile_req.status_code != 200:
            st.error(f"API Error: {profile_req.status_code}")
            st.error(f"FMP Message: {profile_req.text}") # <--- THIS IS THE KEY
            return None
        
        # If profile works, try the others
        metrics_req = requests.get(f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{ticker}?apikey={API_KEY}")
        cf_req = requests.get(f"https://financialmodelingprep.com/api/v3/cash-flow-statement/{ticker}?limit=1&apikey={API_KEY}")

        # Check for specific endpoint failures
        if metrics_req.status_code != 200:
            st.warning(f"Metrics Endpoint Failed: {metrics_req.text}")
        if cf_req.status_code != 200:
            st.warning(f"Cash Flow Endpoint Failed: {cf_req.text}")

        profile = profile_req.json()[0]
        metrics = metrics_req.json()[0]
        cf = cf_req.json()[0]

        return {
            "price": profile['price'],
            "name": profile['companyName'],
            "image": profile['image'],
            "description": profile['description'],
            "shares_out": profile['mktCap'] / profile['price'],
            "net_debt": metrics['netDebtPerShare'] * (profile['mktCap'] / profile['price']),
            "fcf": cf['freeCashFlow'],
            "beta": profile['beta']
        }
    except Exception as e:
        st.error(f"Python Error: {str(e)}")
        return None

# --- 2. DCF LOGIC ---
def calculate_dcf(fcf, growth_rate, wacc, terminal_growth, shares, net_debt):
    future_fcf = []
    for i in range(1, 6):
        fcf = fcf * (1 + growth_rate)
        future_fcf.append(fcf)
    
    terminal_value = (future_fcf[-1] * (1 + terminal_growth)) / (wacc - terminal_growth)
    
    discount_factors = [(1 + wacc) ** i for i in range(1, 6)]
    pv_fcf = sum([f / d for f, d in zip(future_fcf, discount_factors)])
    
    pv_terminal = terminal_value / ((1 + wacc) ** 5)
    
    equity_value = (pv_fcf + pv_terminal) - net_debt
    return equity_value / shares

# --- 3. UI LAYOUT ---
st.title("📊 Intelligent DCF Modeler")

with st.sidebar:
    st.header("Settings")
    ticker = st.text_input("Ticker Symbol", "AAPL").upper()
    if st.button("Analyze Stock"):
        data = get_company_data(ticker)
        if data:
            st.session_state['data'] = data
        else:
            st.error("Ticker not found or API limit reached.")

if 'data' in st.session_state:
    data = st.session_state['data']
    
    # Header
    c1, c2 = st.columns([1, 4])
    with c1: st.image(data['image'], width=80)
    with c2: 
        st.subheader(f"{data['name']} ({ticker})")
        st.metric("Current Price", f"${data['price']}")

    st.markdown("---")
    
    # Scenarios
    st.subheader("⚙️ Scenario Tuning")
    sc1, sc2, sc3 = st.columns(3)
    
    with sc1:
        st.info("🐻 Bear Case")
        bear_g = st.number_input("Bear Growth %", 5.0) / 100
        bear_w = st.number_input("Bear WACC %", 12.0) / 100
        
    with sc2:
        st.success("🏁 Base Case")
        base_g = st.number_input("Base Growth %", 10.0) / 100
        base_w = st.number_input("Base WACC %", 10.0) / 100
        
    with sc3:
        st.warning("🐂 Bull Case")
        bull_g = st.number_input("Bull Growth %", 15.0) / 100
        bull_w = st.number_input("Bull WACC %", 9.0) / 100

    # Global Inputs
    st.markdown("---")
    u1, u2 = st.columns(2)
    with u1: term_g = st.slider("Terminal Growth %", 1.0, 5.0, 2.5) / 100
    with u2: fcf_val = st.number_input("FCF (TTM)", value=float(data['fcf']))

    # Calc
    bear_p = calculate_dcf(fcf_val, bear_g, bear_w, term_g, data['shares_out'], data['net_debt'])
    base_p = calculate_dcf(fcf_val, base_g, base_w, term_g, data['shares_out'], data['net_debt'])
    bull_p = calculate_dcf(fcf_val, bull_g, bull_w, term_g, data['shares_out'], data['net_debt'])

    # Output
    st.markdown("### 🎯 Valuation Targets")
    o1, o2, o3 = st.columns(3)
    
    def get_color(target, current): return "green" if target > current else "red"
    
    o1.metric("Bear Target", f"${bear_p:.2f}", f"{((bear_p-data['price'])/data['price'])*100:.1f}%")
    o2.metric("Base Target", f"${base_p:.2f}", f"{((base_p-data['price'])/data['price'])*100:.1f}%")
    o3.metric("Bull Target", f"${bull_p:.2f}", f"{((bull_p-data['price'])/data['price'])*100:.1f}%")

    # Risk/Reward
    st.markdown("### ⚖️ Risk/Reward")
    upside = bull_p - data['price']
    downside = data['price'] - bear_p
    ratio = upside / downside if downside > 0 else 100
    
    st.metric("Risk/Reward Ratio", f"{ratio:.2f} : 1")
    if ratio > 3: st.success("Strong Buy Territory (>3:1)")
    elif ratio > 1.5: st.warning("Moderate Buy Territory")
    else: st.error("High Risk / Low Reward")
