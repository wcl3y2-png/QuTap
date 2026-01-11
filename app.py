import streamlit as st
import yfinance as yf
import pandas as pd
import numpy_financial as npf

# --- PAGE CONFIG ---
st.set_page_config(page_title="DCF Master", layout="wide")

# --- 1. DATA FETCHING (VIA YAHOO FINANCE) ---
def get_company_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # Check if data exists
        if 'currentPrice' not in info:
            st.error(f"Could not fetch data for {ticker}. Is the symbol correct?")
            return None

        # 1. PRICE & SHARES
        price = info.get('currentPrice', 0)
        shares = info.get('sharesOutstanding', 0)
        name = info.get('longName', ticker)
        
        # 2. FINANCIAL STATEMENTS (DataFrame format)
        # We use .iloc[:, 0] to get the most recent column (latest year)
        bs = stock.balance_sheet
        cf = stock.cashflow
        
        if bs.empty or cf.empty:
            st.warning("Financial statements not found. Using partial data.")
            return None

        # 3. CALCULATE NET DEBT
        # Try different naming conventions Yahoo uses
        try:
            total_debt = bs.loc['Total Debt'].iloc[0]
        except KeyError:
            # Fallback if specific line item is missing
            total_debt = 0
            
        try:
            cash = bs.loc['Cash And Cash Equivalents'].iloc[0]
        except KeyError:
            cash = 0
            
        net_debt = total_debt - cash

        # 4. CALCULATE FCF (Operating Cash Flow - CapEx)
        try:
            ocf = cf.loc['Operating Cash Flow'].iloc[0]
            # CapEx is usually negative in Yahoo, so we ADD it to subtract the value
            capex = cf.loc['Capital Expenditure'].iloc[0] 
            fcf = ocf + capex
        except KeyError:
            # Fallback to Free Cash Flow field if manual calc fails
            fcf = cf.loc['Free Cash Flow'].iloc[0] if 'Free Cash Flow' in cf.index else 0

        return {
            "price": price,
            "name": name,
            "image": info.get('logo_url', ''), # Yahoo often doesn't send logos, so this might be blank
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
st.title("📊 Intelligent DCF Modeler (Powered by Yahoo)")

with st.sidebar:
    st.header("Settings")
    ticker = st.text_input("Ticker Symbol", "AAPL").upper()
    if st.button("Analyze Stock"):
        with st.spinner(f'Pulling data for {ticker}...'):
            data = get_company_data(ticker)
            if data:
                st.session_state['data'] = data

if 'data' in st.session_state:
    data = st.session_state['data']
    
    # Header
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