import streamlit as st
import requests
import pandas as pd
import numpy_financial as npf

# --- PAGE CONFIG ---
st.set_page_config(page_title="DCF Master", layout="wide")

# --- API SETUP ---
try:
    API_KEY = st.secrets["FMP_API_KEY"]
except FileNotFoundError:
    st.error("API Key not found. Please set FMP_API_KEY in secrets.")
    st.stop()

# --- 1. DATA FETCHING (FREE TIER COMPATIBLE) ---
def get_company_data(ticker):
    if not API_KEY: return None
    
    try:
        # 1. Get Quote (Price, Name, Shares) - usually robust on free tier
        quote_url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={API_KEY}"
        quote_req = requests.get(quote_url)
        
        # 2. Get Balance Sheet (For Net Debt) - Standard Annual
        bs_url = f"https://financialmodelingprep.com/api/v3/balance-sheet-statement/{ticker}?period=annual&limit=1&apikey={API_KEY}"
        bs_req = requests.get(bs_url)
        
        # 3. Get Cash Flow (For FCF) - Standard Annual
        cf_url = f"https://financialmodelingprep.com/api/v3/cash-flow-statement/{ticker}?period=annual&limit=1&apikey={API_KEY}"
        cf_req = requests.get(cf_url)

        # ERROR HANDLING
        if quote_req.status_code != 200:
            st.error(f"Quote API Error: {quote_req.text}")
            return None
            
        quote_data = quote_req.json()
        if not quote_data:
            st.error("Ticker not found.")
            return None
        quote = quote_data[0]
        
        # If statements are empty (e.g. ETFs or new listings), handle gracefully
        bs_data = bs_req.json()
        cf_data = cf_req.json()
        
        if not bs_data or not cf_data:
            st.error("Financial statements not found for this ticker (might be an ETF?).")
            return None

        bs = bs_data[0]
        cf = cf_data[0]

        # --- MANUAL CALCULATIONS (Bypassing Premium Endpoints) ---
        
        # Net Debt = (Short Term Debt + Long Term Debt) - (Cash + Equivalents)
        # Note: FMP field names can vary, using standard safe gets
        short_debt = bs.get('shortTermDebt', 0)
        long_debt = bs.get('longTermDebt', 0)
        cash = bs.get('cashAndCashEquivalents', 0)
        net_debt_calc = (short_debt + long_debt) - cash
        
        # FCF = Operating Cash Flow - Capital Expenditure
        ocf = cf.get('operatingCashFlow', 0)
        capex = cf.get('capitalExpenditure', 0)
        fcf_calc = ocf - capex # Note: CapEx is usually negative in statements, but FMP returns it as negative. 
        # Standard Formula: OCF - CapEx. If FMP gives negative CapEx, we add it? 
        # FMP 'freeCashFlow' field is usually reliable in the statement itself.
        fcf_final = cf.get('freeCashFlow', ocf + capex) 

        return {
            "price": quote.get('price', 0),
            "name": quote.get('name', ticker),
            "image": f"https://financialmodelingprep.com/image-stock/{ticker}.png", # Construct image URL manually to save a call
            "description": "Description unavailable in free mode", # Profile endpoint is often legacy now
            "shares_out": quote.get('sharesOutstanding', 0),
            "net_debt": net_debt_calc, # Total Net Debt (not per share)
            "fcf": fcf_final,
            "beta": 0 # Beta is often in profile (legacy), setting to 0 or manual input
        }

    except Exception as e:
        st.error(f"Data Parse Error: {str(e)}")
        return None

# --- 2. DCF LOGIC ---
def calculate_dcf(fcf, growth_rate, wacc, terminal_growth, shares, net_debt):
    if shares == 0: return 0
    
    future_fcf = []
    current_fcf = fcf
    
    for i in range(1, 6):
        current_fcf = current_fcf * (1 + growth_rate)
        future_fcf.append(current_fcf)
    
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
        with st.spinner('Fetching financial statements...'):
            data = get_company_data(ticker)
            if data:
                st.session_state['data'] = data

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
    with u2: fcf_val = st.number_input("FCF (Latest Annual)", value=float(data['fcf']))

    # Calc
    bear_p = calculate_dcf(fcf_val, bear_g, bear_w, term_g, data['shares_out'], data['net_debt'])
    base_p = calculate_dcf(fcf_val, base_g, base_w, term_g, data['shares_out'], data['net_debt'])
    bull_p = calculate_dcf(fcf_val, bull_g, bull_w, term_g, data['shares_out'], data['net_debt'])

    # Output
    st.markdown("### 🎯 Valuation Targets")
    o1, o2, o3 = st.columns(3)
    
    # Avoid div/0 if price is 0
    safe_price = data['price'] if data['price'] > 0 else 1
    
    o1.metric("Bear Target", f"${bear_p:.2f}", f"{((bear_p-safe_price)/safe_price)*100:.1f}%")
    o2.metric("Base Target", f"${base_p:.2f}", f"{((base_p-safe_price)/safe_price)*100:.1f}%")
    o3.metric("Bull Target", f"${bull_p:.2f}", f"{((bull_p-safe_price)/safe_price)*100:.1f}%")

    # Risk/Reward
    st.markdown("### ⚖️ Risk/Reward")
    upside = bull_p - safe_price
    downside = safe_price - bear_p
    
    if downside <= 0:
        ratio = 100
        rr_text = "No modeled downside"
    else:
        ratio = upside / downside
        rr_text = f"{ratio:.2f} : 1"
    
    st.metric("Risk/Reward Ratio", rr_text)
    if ratio > 3: st.success("Strong Buy Territory (>3:1)")
    elif ratio > 1.5: st.warning("Moderate Buy Territory")
    else: st.error("High Risk / Low Reward")