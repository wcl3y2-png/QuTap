import streamlit as st
import yfinance as yf
import pandas as pd
import numpy_financial as npf

# --- CONFIGURATION ---
st.set_page_config(page_title="Smart DCF Modeler", layout="wide")

# --- 0. INDUSTRY LOGIC ENGINE ---
def get_industry_defaults(sector):
    """Returns default WACC and Growth presets based on Sector."""
    # Default: Moderate Risk/Growth
    defaults = {
        "bear_g": 5.0, "base_g": 10.0, "bull_g": 15.0,
        "bear_w": 10.0, "base_w": 9.0, "bull_w": 8.0
    }
    
    if not sector: return defaults

    sector = sector.lower()
    
    if "technology" in sector:
        # High Growth, Higher Volatility
        return {
            "bear_g": 8.0, "base_g": 14.0, "bull_g": 20.0,
            "bear_w": 11.0, "base_w": 10.0, "bull_w": 9.0
        }
    elif "utilities" in sector or "energy" in sector:
        # Low Growth, Low Risk (Stable Cash Flows)
        return {
            "bear_g": 1.0, "base_g": 3.0, "bull_g": 5.0,
            "bear_w": 7.0, "base_w": 6.0, "bull_w": 5.0
        }
    elif "healthcare" in sector:
        # Moderate/High Growth, Moderate Risk
        return {
            "bear_g": 4.0, "base_g": 8.0, "bull_g": 12.0,
            "bear_w": 9.0, "base_w": 8.0, "bull_w": 7.0
        }
    elif "consumer defensive" in sector:
        # Slow Growth, Safe
        return {
            "bear_g": 2.0, "base_g": 5.0, "bull_g": 7.0,
            "bear_w": 7.5, "base_w": 6.5, "bull_w": 6.0
        }
    elif "financial" in sector or "real estate" in sector:
        # Rate Sensitive
        return {
            "bear_g": 3.0, "base_g": 6.0, "bull_g": 9.0,
            "bear_w": 10.0, "base_w": 8.5, "bull_w": 7.5
        }
        
    return defaults

# --- 1. DATA FETCHING ---
def get_company_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        if 'currentPrice' not in info:
            st.error(f"Could not fetch data for {ticker}. Is the symbol correct?")
            return None

        # Basic Info
        price = info.get('currentPrice', 0)
        shares = info.get('sharesOutstanding', 0)
        name = info.get('longName', ticker)
        sector = info.get('sector', 'Unknown')
        peg_ratio = info.get('pegRatio', None)
        
        # Financial Statements
        bs = stock.balance_sheet
        cf = stock.cashflow
        
        if bs.empty or cf.empty:
            st.warning("Financial statements not found. Using partial data.")
            return None

        # Net Debt Calculation
        try:
            total_debt = bs.loc['Total Debt'].iloc[0]
        except KeyError:
            total_debt = 0
        try:
            cash = bs.loc['Cash And Cash Equivalents'].iloc[0]
        except KeyError:
            cash = 0
        net_debt = total_debt - cash

        # FCF Calculation
        try:
            ocf = cf.loc['Operating Cash Flow'].iloc[0]
            capex = cf.loc['Capital Expenditure'].iloc[0]
            fcf = ocf + capex
        except KeyError:
            fcf = cf.loc['Free Cash Flow'].iloc[0] if 'Free Cash Flow' in cf.index else 0

        return {
            "price": price,
            "name": name,
            "sector": sector,
            "peg_ratio": peg_ratio,
            "image": info.get('logo_url', ''),
            "description": info.get('longBusinessSummary', 'No description'),
            "shares_out": shares,
            "net_debt": net_debt,
            "fcf": fcf,
            "beta": info.get('beta', 1.0)
        }

    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
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
    st.header("Analysis Settings")
    ticker = st.text_input("Ticker Symbol", "NVDA").upper()
    if st.button("Analyze Stock"):
        with st.spinner(f'Analyzing {ticker} ecosystem...'):
            data = get_company_data(ticker)
            if data:
                st.session_state['data'] = data
                # Reset defaults when loading new ticker
                st.session_state['defaults'] = get_industry_defaults(data['sector'])

if 'data' in st.session_state:
    data = st.session_state['data']
    defaults = st.session_state.get('defaults', get_industry_defaults(None))
    
    # --- HEADER SECTION ---
    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader(f"{data['name']} ({ticker})")
        st.caption(f"Sector: {data['sector']}")
    with c2:
        st.metric("Current Price", f"${data['price']}")

    # --- KEY METRICS BAR ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("PEG Ratio", f"{data['peg_ratio']}" if data['peg_ratio'] else "N/A")
    m2.metric("Beta", f"{data['beta']:.2f}")
    m3.metric("FCF (Billions)", f"${data['fcf']/1e9:.2f}B")
    
    # Dynamic logic for Net Debt color
    debt_color = "normal"
    if data['net_debt'] < 0: debt_str = f"Cash Rich: ${abs(data['net_debt'])/1e9:.2f}B"
    else: debt_str = f"Net Debt: ${data['net_debt']/1e9:.2f}B"
    m4.metric("Balance Sheet", debt_str)

    st.markdown("---")
    
    # --- SCENARIO TUNING ---
    st.subheader("⚙️ Scenario Assumptions (Auto-Tuned by Sector)")
    
    sc1, sc2, sc3 = st.columns(3)
    
    # We use 'key' in widgets to persist values, but 'value' sets the initial default
    with sc1:
        st.info("🐻 Bear Case")
        bear_g = st.number_input("Bear Growth %", value=defaults["bear_g"], step=0.5, key="b_g") / 100
        bear_w = st.number_input("Bear WACC %", value=defaults["bear_w"], step=0.5, key="b_w") / 100
        
    with sc2:
        st.success("🏁 Base Case")
        base_g = st.number_input("Base Growth %", value=defaults["base_g"], step=0.5, key="ba_g") / 100
        base_w = st.number_input("Base WACC %", value=defaults["base_w"], step=0.5, key="ba_w") / 100
        
    with sc3:
        st.warning("🐂 Bull Case")
        bull_g = st.number_input("Bull Growth %", value=defaults["bull_g"], step=0.5, key="bu_g") / 100
        bull_w = st.number_input("Bull WACC %", value=defaults["bull_w"], step=0.5, key="bu_w") / 100

    # Global Inputs
    st.markdown("---")
    u1, u2 = st.columns(2)
    with u1: term_g = st.slider("Terminal Growth Rate %", 1.0, 5.0, 2.5) / 100
    with u2: fcf_val = st.number_input("Free Cash Flow Input", value=float(data['fcf']))

    # --- CALCULATIONS ---
    bear_p = calculate_dcf(fcf_val, bear_g, bear_w, term_g, data['shares_out'], data['net_debt'])
    base_p = calculate_dcf(fcf_val, base_g, base_w, term_g, data['shares_out'], data['net_debt'])
    bull_p = calculate_dcf(fcf_val, bull_g, bull_w, term_g, data['shares_out'], data['net_debt'])

    # --- OUTPUT ---
    st.markdown("### 🎯 Valuation Targets")
    o1, o2, o3 = st.columns(3)
    
    safe_price = data['price'] if data['price'] > 0 else 1
    
    def fmt_upside(target):
        pct = ((target - safe_price) / safe_price) * 100
        return f"{pct:+.1f}%"

    o1.metric("Bear Target", f"${bear_p:.2f}", fmt_upside(bear_p))
    o2.metric("Base Target", f"${base_p:.2f}", fmt_upside(base_p))
    o3.metric("Bull Target", f"${bull_p:.2f}", fmt_upside(bull_p))

    # --- RISK / REWARD ---
    st.markdown("### ⚖️ Risk/Reward Analysis")
    upside = bull_p - safe_price
    downside = safe_price - bear_p
    
    if downside <= 0:
        ratio = 100
        rr_text = "Infinite (No modeled downside)"
    else:
        ratio = upside / downside
        rr_text = f"{ratio:.2f} : 1"
    
    col_rr, col_desc = st.columns([1, 3])
    col_rr.metric("Risk/Reward Ratio", rr_text)
    
    with col_desc:
        if ratio > 3: 
            st.success(f"**Strong Opportunity**: For every $1 you risk losing (Bear Case), you could make ${ratio:.2f} (Bull Case).")
        elif ratio > 1.5: 
            st.warning(f"**Moderate Opportunity**: Upside outweighs downside, but margin is slim.")
        else: 
            st.error(f"**Unattractive Entry**: You are risking $1 to make only ${ratio:.2f}.")