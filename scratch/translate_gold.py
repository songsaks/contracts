import sys
import re

# Set stdout encoding
sys.stdout.reconfigure(encoding='utf-8')

file_path = 'stocks/templates/stocks/gold_trading.html'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Precise Block Replacements
blocks = [
    # Title
    (
        "{% block title %}Gold Command Center · XAU/USD{% endblock %}",
        "{% block title %}ศูนย์บัญชาการบอททองคำ · XAU/USD{% endblock %}"
    ),
    
    # News Flash
    (
        '<div id="news-flash-box" class="news-fade-in">Loading market news...</div>',
        '<div id="news-flash-box" class="news-fade-in">กำลังโหลดข่าวสารตลาดทองคำ...</div>'
    ),
    
    # Header block
    (
        '''<!-- ══════ HEADER ══════ -->
<div class="gcc-header d-flex flex-wrap justify-content-between align-items-center gap-2">
    <div>
        <h1><i class="fas fa-coins me-2"></i>GOLD COMMAND CENTER <span style="font-size: 0.5em; background: rgba(16, 185, 129, 0.2); color: #34d399; padding: 2px 8px; border-radius: 4px; vertical-align: middle;">v2.1 SafeMode</span></h1>
        <div class="gcc-subtitle d-none d-sm-block">XAU/USD · Turtle Breakout Strategy · Spot Gold</div>
    </div>
    <div class="d-flex align-items-center gap-2">
        <span class="status-pill pill-standby" id="bot-status-indicator">● STANDBY</span>
        <button class="btn btn-sm btn-outline-warning fw-bold rounded-pill" onclick="toggleAiStrategist()">
            <i class="fas fa-robot me-1"></i><span class="d-none d-sm-inline"> Robot</span>
        </button>
        <button class="btn btn-sm fw-bold rounded-pill d-none d-lg-inline-flex" style="background:var(--gold);color:#000;" onclick="toggleFullscreen()">
            <i class="fas fa-expand me-1"></i> Fullscreen
        </button>
    </div>
</div>''',
        '''<!-- ══════ HEADER ══════ -->
<div class="gcc-header d-flex flex-wrap justify-content-between align-items-center gap-2">
    <div>
        <h1><i class="fas fa-coins me-2"></i>ศูนย์บัญชาการบอททองคำ <span style="font-size: 0.5em; background: rgba(16, 185, 129, 0.2); color: #34d399; padding: 2px 8px; border-radius: 4px; vertical-align: middle;">v2.1 SafeMode</span></h1>
        <div class="gcc-subtitle d-none d-sm-block">XAU/USD · กลยุทธ์ Turtle Breakout · Spot Gold</div>
    </div>
    <div class="d-flex align-items-center gap-2">
        <span class="status-pill pill-standby" id="bot-status-indicator">● STANDBY</span>
        <button class="btn btn-sm btn-outline-warning fw-bold rounded-pill" onclick="toggleAiStrategist()">
            <i class="fas fa-robot me-1"></i><span class="d-none d-sm-inline"> โรบอทวิเคราะห์</span>
        </button>
        <button class="btn btn-sm fw-bold rounded-pill d-none d-lg-inline-flex" style="background:var(--gold);color:#000;" onclick="toggleFullscreen()">
            <i class="fas fa-expand me-1"></i> เต็มหน้าจอ
        </button>
    </div>
</div>'''
    ),
    
    # Sticky price bar
    (
        '<span id="m-signal" class="signal-badge" style="background:#334155;color:#94a3b8;font-size:0.78rem;padding:5px 12px;">NEUTRAL</span>',
        '<span id="m-signal" class="signal-badge" style="background:#334155;color:#94a3b8;font-size:0.78rem;padding:5px 12px;">รอยืนยันสัญญาณ</span>'
    ),
    
    # Order execution card
    (
        '''        <!-- ORDER EXECUTION -->
        <div class="g-card g-card-dark">
            <div class="g-card-header">
                <i class="fas fa-bolt" style="color:var(--gold)"></i> ORDER EXECUTION
            </div>
            <div class="p-3 d-flex flex-column gap-2">
                <div class="d-flex gap-2">
                    <button class="btn-execute-buy flex-grow-1" onclick="executeTrade('BUY')">
                        <i class="fas fa-arrow-trend-up me-2"></i> BUY
                    </button>
                    <button class="btn-execute-sell flex-grow-1" onclick="executeTrade('SELL')">
                        <i class="fas fa-arrow-trend-down me-2"></i> SELL
                    </button>
                </div>
                <button class="btn btn-sm w-100 fw-bold" onclick="closeAllPositions()"
                    style="background:transparent;border:1px solid rgba(248,81,73,0.35);color:rgba(248,81,73,0.8);border-radius:8px;padding:8px;font-size:0.78rem;cursor:pointer;">
                    <i class="fas fa-times-circle me-1"></i> CLOSE ALL POSITIONS
                </button>
            </div>
        </div>''',
        '''        <!-- ORDER EXECUTION -->
        <div class="g-card g-card-dark">
            <div class="g-card-header">
                <i class="fas fa-bolt" style="color:var(--gold)"></i> ส่งคำสั่งซื้อขาย (MANUAL)
            </div>
            <div class="p-3 d-flex flex-column gap-2">
                <div class="d-flex gap-2">
                    <button class="btn-execute-buy flex-grow-1" onclick="executeTrade('BUY')">
                        <i class="fas fa-arrow-trend-up me-2"></i> ซื้อ (BUY)
                    </button>
                    <button class="btn-execute-sell flex-grow-1" onclick="executeTrade('SELL')">
                        <i class="fas fa-arrow-trend-down me-2"></i> ขาย (SELL)
                    </button>
                </div>
                <button class="btn btn-sm w-100 fw-bold" onclick="closeAllPositions()"
                    style="background:transparent;border:1px solid rgba(248,81,73,0.35);color:rgba(248,81,73,0.8);border-radius:8px;padding:8px;font-size:0.78rem;cursor:pointer;">
                    <i class="fas fa-times-circle me-1"></i> ปิดสถานะทั้งหมด (CLOSE ALL)
                </button>
            </div>
        </div>'''
    ),
    
    # Position Sizer decision support panel
    (
        '''                <!-- Tactical Decision Center -->
                <div id="decision-center" class="decision-panel wait d-flex align-items-center">
                    <div class="pulse-ring" id="signal-pulse"></div>
                    <div class="signal-icon" id="signal-main-icon"><i class="fas fa-satellite-dish" style="color:var(--text-lo)"></i></div>
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <div style="font-size:0.58rem;color:var(--text-lo);text-transform:uppercase;letter-spacing:1px;margin-bottom:2px;">Decision Support</div>
                                <div class="signal-status" id="signal-main-text">SCANNING...</div>
                                <div class="signal-message" id="signal-main-subtext">Monitoring breakout levels.</div>
                            </div>
                            <span class="badge" id="active-strategy-badge" style="background:rgba(255,255,255,0.05);border:1px solid var(--border);font-size:0.58rem;padding:3px 8px;">
                                MODE: <span id="display-strategy">SNIPER</span>
                            </span>
                        </div>
                    </div>
                </div>''',
        '''                <!-- Tactical Decision Center -->
                <div id="decision-center" class="decision-panel wait d-flex align-items-center">
                    <div class="pulse-ring" id="signal-pulse"></div>
                    <div class="signal-icon" id="signal-main-icon"><i class="fas fa-satellite-dish" style="color:var(--text-lo)"></i></div>
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <div style="font-size:0.58rem;color:var(--text-lo);text-transform:uppercase;letter-spacing:1px;margin-bottom:2px;">ระบบช่วยตัดสินใจ</div>
                                <div class="signal-status" id="signal-main-text">กำลังสแกน...</div>
                                <div class="signal-message" id="signal-main-subtext">เฝ้าระวังจุด Breakout</div>
                            </div>
                            <span class="badge" id="active-strategy-badge" style="background:rgba(255,255,255,0.05);border:1px solid var(--border);font-size:0.58rem;padding:3px 8px;">
                                กลยุทธ์: <span id="display-strategy">SNIPER</span>
                            </span>
                        </div>
                    </div>
                </div>'''
    ),
    
    # Capital, Risk, Suggested Size, Manual Override, Signal Feed
    (
        '''                <div class="row g-2 mt-1">
                    <div class="col-6">
                        <label class="matrix-label d-block mb-1">CAPITAL ($)</label>
                        <input type="number" id="capital-input" class="form-control form-control-sm fw-bold text-center" value="{{ capital|floatformat:2 }}"
                            style="background:var(--bg-input);color:var(--text-hi);border-color:var(--border);">
                    </div>
                    <div class="col-6">
                        <label class="matrix-label d-block mb-1">RISK (%)</label>
                        <input type="number" id="risk-pct" class="form-control form-control-sm fw-bold text-center" value="1"
                            style="background:var(--bg-input);color:var(--text-hi);border-color:var(--border);">
                    </div>
                </div>

                <div class="sizer-suggested">
                    <div class="sizer-label">SUGGESTED SIZE</div>
                    <div class="sizer-value" id="tac-suggest-size">0.00 Lots</div>
                </div>

                <div class="mt-2">
                    <label class="matrix-label d-block mb-1">MANUAL OVERRIDE (LOTS)</label>
                    <input type="number" id="manual-lot-input" class="form-control form-control-sm fw-bold text-center"
                        placeholder="Leave empty for suggested" step="0.01"
                        style="background:rgba(240,183,47,0.05);color:var(--gold);border-color:rgba(240,183,47,0.3);">
                    <div class="text-center mt-1" style="font-size:0.6rem;color:var(--text-lo);">*Max safety cap: 0.05 (Default)</div>
                </div>

                <div class="d-flex justify-content-between mt-2 pt-2" style="border-top:1px solid var(--border);">
                    <div class="text-center flex-grow-1">
                        <div class="matrix-label" style="font-size:0.58rem;">TREND (EMA200)</div>
                        <div id="trend-status-display" class="fw-bold" style="font-size:0.8rem;color:var(--green);">BULLISH</div>
                    </div>
                    <div class="text-center flex-grow-1" style="border-left:1px solid var(--border);">
                        <div class="matrix-label" style="font-size:0.58rem;">RSI (14)</div>
                        <div id="rsi-display" class="fw-bold" style="font-size:0.8rem;color:var(--blue);">--</div>
                    </div>
                </div>

                <div class="mt-3">
                    <div style="font-size:0.6rem;font-weight:800;color:var(--text-lo);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
                        <i class="fas fa-comment-alt me-1"></i> SIGNAL FEED
                    </div>
                    <div id="signal-feed" class="message-feed">
                        <div class="feed-entry"><span class="feed-time">[SYSTEM]</span> <span class="feed-msg">Initializing...</span></div>
                    </div>
                </div>''',
        '''                <div class="row g-2 mt-1">
                    <div class="col-6">
                        <label class="matrix-label d-block mb-1">เงินทุน ($)</label>
                        <input type="number" id="capital-input" class="form-control form-control-sm fw-bold text-center" value="{{ capital|floatformat:2 }}"
                            style="background:var(--bg-input);color:var(--text-hi);border-color:var(--border);">
                    </div>
                    <div class="col-6">
                        <label class="matrix-label d-block mb-1">ความเสี่ยง (%)</label>
                        <input type="number" id="risk-pct" class="form-control form-control-sm fw-bold text-center" value="1"
                            style="background:var(--bg-input);color:var(--text-hi);border-color:var(--border);">
                    </div>
                </div>

                <div class="sizer-suggested">
                    <div class="sizer-label">ขนาดไม้แนะนำ</div>
                    <div class="sizer-value" id="tac-suggest-size">0.00 Lots</div>
                </div>

                <div class="mt-2">
                    <label class="matrix-label d-block mb-1">ระบุเอง (MANUAL LOTS)</label>
                    <input type="number" id="manual-lot-input" class="form-control form-control-sm fw-bold text-center"
                        placeholder="ปล่อยว่างไว้เพื่อใช้ค่าคำนวณข้างต้น" step="0.01"
                        style="background:rgba(240,183,47,0.05);color:var(--gold);border-color:rgba(240,183,47,0.3);">
                    <div class="text-center mt-1" style="font-size:0.6rem;color:var(--text-lo);">*จำกัดความปลอดภัยสูงสุด: 0.05 Lots</div>
                </div>

                <div class="d-flex justify-content-between mt-2 pt-2" style="border-top:1px solid var(--border);">
                    <div class="text-center flex-grow-1">
                        <div class="matrix-label" style="font-size:0.58rem;">แนวโน้ม (EMA200)</div>
                        <div id="trend-status-display" class="fw-bold" style="font-size:0.8rem;color:var(--green);">BULLISH</div>
                    </div>
                    <div class="text-center flex-grow-1" style="border-left:1px solid var(--border);">
                        <div class="matrix-label" style="font-size:0.58rem;">ดัชนี RSI (14)</div>
                        <div id="rsi-display" class="fw-bold" style="font-size:0.8rem;color:var(--blue);">--</div>
                    </div>
                </div>

                <div class="mt-3">
                    <div style="font-size:0.6rem;font-weight:800;color:var(--text-lo);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
                        <i class="fas fa-comment-alt me-1"></i> ฟีดสัญญาณ Breakout
                    </div>
                    <div id="signal-feed" class="message-feed">
                        <div class="feed-entry"><span class="feed-time">[ระบบ]</span> <span class="feed-msg">กำลังเริ่มต้นระบบ...</span></div>
                    </div>
                </div>'''
    ),
    
    # Signal Matrix
    (
        '''        <!-- SIGNAL MATRIX -->
        <div class="g-card g-card-dark" id="strategic-matrix-box">
            <div class="g-card-header">
                <i class="fas fa-satellite-dish" style="color:var(--blue)"></i> SIGNAL MATRIX
            </div>
            <div class="matrix-row">
                <span class="matrix-label">SNIPER (DC10)</span>
                <span id="sig-sniper" class="matrix-btn wait">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">SCALPER (DC10)</span>
                <span id="sig-short" class="matrix-btn wait">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">SWING (DC20)</span>
                <span id="sig-medium" class="matrix-btn wait">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">TURTLE (DC55)</span>
                <span id="sig-long" class="matrix-btn wait">WAIT</span>
            </div>
        </div>''',
        '''        <!-- SIGNAL MATRIX -->
        <div class="g-card g-card-dark" id="strategic-matrix-box">
            <div class="g-card-header">
                <i class="fas fa-satellite-dish" style="color:var(--blue)"></i> ตารางสัญญาณ Breakout
            </div>
            <div class="matrix-row">
                <span class="matrix-label">สไนเปอร์ (DC10)</span>
                <span id="sig-sniper" class="matrix-btn wait">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">สแคลเปอร์ (DC10)</span>
                <span id="sig-short" class="matrix-btn wait">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">สวิงเทรด (DC20)</span>
                <span id="sig-medium" class="matrix-btn wait">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">เทอร์เทิล (DC55)</span>
                <span id="sig-long" class="matrix-btn wait">WAIT</span>
            </div>
        </div>'''
    ),
    
    # Volume Breakout header
    (
        '''        <!-- VOLUME CONFIRMATION -->
        <div class="g-card g-card-dark" id="vol-confirm-card">
            <div class="g-card-header">
                <i class="fas fa-chart-bar" style="color:var(--gold)"></i> VOLUME BREAKOUT
            </div>''',
        '''        <!-- VOLUME CONFIRMATION -->
        <div class="g-card g-card-dark" id="vol-confirm-card">
            <div class="g-card-header">
                <i class="fas fa-chart-bar" style="color:var(--gold)"></i> ปริมาณการซื้อขาย (VOLUME BREAKOUT)
            </div>'''
    ),
    
    # Market Sentiment Card
    (
        '''        <!-- MARKET SENTIMENT -->
        <div class="g-card g-card-dark">
            <div class="g-card-header">
                <i class="fas fa-globe-americas" style="color:var(--blue)"></i> MARKET SENTIMENT
            </div>
            <div class="matrix-row">
                <span class="matrix-label">DXY INDEX</span>
                <span id="dxy-status" class="status-pill pill-standby">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">MTF ALIGNMENT</span>''',
        '''        <!-- MARKET SENTIMENT -->
        <div class="g-card g-card-dark">
            <div class="g-card-header">
                <i class="fas fa-globe-americas" style="color:var(--blue)"></i> อารมณ์ตลาด (SENTIMENT)
            </div>
            <div class="matrix-row">
                <span class="matrix-label">ดัชนีดอลลาร์ (DXY)</span>
                <span id="dxy-status" class="status-pill pill-standby">WAIT</span>
            </div>
            <div class="matrix-row">
                <span class="matrix-label">แนวโน้มหลายกรอบเวลา (MTF)</span>'''
    ),
    
    # AI Strategist advice box
    (
        '''            <div class="p-3" style="background:rgba(0,0,0,0.2);border-top:1px solid var(--border);">
                <div class="d-flex align-items-center mb-2">
                    <i class="fas fa-robot me-2" style="color:var(--blue);font-size:0.75rem;"></i>
                    <span style="font-size:0.62rem;font-weight:800;color:var(--blue);letter-spacing:1px;text-transform:uppercase;">AI STRATEGIST</span>
                </div>
                <div id="ai-sentiment-advice" style="font-size:0.78rem;color:var(--text-hi);line-height:1.55;font-family:'Outfit',sans-serif;">กำลังประมวลผล...</div>
            </div>''',
        '''            <div class="p-3" style="background:rgba(0,0,0,0.25);border-top:1px solid var(--border);">
                <div class="d-flex align-items-center mb-2">
                    <i class="fas fa-robot me-2" style="color:var(--blue);font-size:0.75rem;"></i>
                    <span style="font-size:0.62rem;font-weight:800;color:var(--blue);letter-spacing:1px;text-transform:uppercase;">วิเคราะห์ด้วย AI</span>
                </div>
                <div id="ai-sentiment-advice" style="font-size:0.78rem;color:var(--text-hi);line-height:1.55;font-family:'Outfit',sans-serif;">กำลังวิเคราะห์แนวโน้มราคาทองคำ...</div>
            </div>'''
    ),
    
    # Activity Log card
    (
        '''        <!-- ACTIVITY LOG -->
        <div class="g-card g-card-dark">
            <div class="g-card-header"><i class="fas fa-terminal" style="color:var(--text-lo)"></i> ACTIVITY LOG</div>
            <div class="log-box" id="bot-logs"></div>
        </div>''',
        '''        <!-- ACTIVITY LOG -->
        <div class="g-card g-card-dark">
            <div class="g-card-header"><i class="fas fa-terminal" style="color:var(--text-lo)"></i> บันทึกระบบ (ACTIVITY LOG)</div>
            <div class="log-box" id="bot-logs"></div>
        </div>'''
    ),
    
    # Chart placeholders
    (
        '<div style="position:absolute;top:8px;left:12px;font-size:10px;font-weight:900;color:#64748b;z-index:10;background:rgba(255,255,255,0.85);padding:2px 6px;border-radius:4px;pointer-events:none;">MAIN CHART</div>',
        '<div style="position:absolute;top:8px;left:12px;font-size:10px;font-weight:900;color:#64748b;z-index:10;background:rgba(255,255,255,0.85);padding:2px 6px;border-radius:4px;pointer-events:none;">กราฟราคาทองคำ</div>'
    ),
    
    # Price and Bot Status (Corrected for blue style in TEST ORDER button)
    (
        '''        <!-- PRICE & BOT STATUS -->
        <div class="price-panel">
            <div class="d-flex justify-content-between align-items-center mb-1">
                <span class="price-symbol">GOLD · XAU/USD</span>
                <span class="price-time" id="last-update-time">Updated: --:--:--</span>
            </div>
            <div class="d-flex align-items-baseline">
                <span class="price-value" id="gold-price-display">----.-</span>
                <span class="price-chg" id="gold-change-display" style="color:var(--text-lo);">+0.00%</span>
            </div>
            <div class="bot-status-bar">
                <div class="bot-indicator">
                    <div class="bot-dot" id="bot-status-lamp"></div>
                    <span id="bot-status-text" style="font-size:0.7rem;">SERVER BOT: OFFLINE</span>
                </div>
                <button id="btn-stop-bot" class="btn-stop-bot">STOP</button>
                <button id="btn-start-bot" class="btn-stop-bot d-none" style="border-color:var(--green);color:var(--green);">START</button>
            </div>
            <div id="tactical-signal" class="tactical-signal-badge">── NEUTRAL ──</div>
            <button class="btn w-100 mt-2" onclick="executeTrade(\'BUY\', false, 0.01)"
                style="border:1px dashed rgba(88,166,255,0.4);color:var(--blue);background:rgba(88,166,255,0.04);font-weight:800;border-radius:8px;font-size:0.78rem;padding:0.5rem;">
                <i class="fas fa-vial me-1"></i> TEST ORDER (0.01 Lot)
            </button>
        </div>''',
        '''        <!-- PRICE & BOT STATUS -->
        <div class="price-panel">
            <div class="d-flex justify-content-between align-items-center mb-1">
                <span class="price-symbol">GOLD · XAU/USD</span>
                <span class="price-time" id="last-update-time">อัปเดตเมื่อ: --:--:--</span>
            </div>
            <div class="d-flex align-items-baseline">
                <span class="price-value" id="gold-price-display">----.-</span>
                <span class="price-chg" id="gold-change-display" style="color:var(--text-lo);">+0.00%</span>
            </div>
            <div class="bot-status-bar">
                <div class="bot-indicator">
                    <div class="bot-dot" id="bot-status-lamp"></div>
                    <span id="bot-status-text" style="font-size:0.7rem;">SERVER BOT: OFFLINE</span>
                </div>
                <button id="btn-stop-bot" class="btn-stop-bot">หยุดระบบ</button>
                <button id="btn-start-bot" class="btn-stop-bot d-none" style="border-color:var(--green);color:var(--green);">เริ่มระบบ</button>
            </div>
            <div id="tactical-signal" class="tactical-signal-badge">── NEUTRAL ──</div>
            <button class="btn w-100 mt-2" onclick="executeTrade(\'BUY\', false, 0.01)"
                style="border:1px dashed rgba(88,166,255,0.4);color:var(--blue);background:rgba(88,166,255,0.04);font-weight:800;border-radius:8px;font-size:0.78rem;padding:0.5rem;">
                <i class="fas fa-vial me-1"></i> ส่งคำสั่งทดสอบ (0.01 Lot)
            </button>
        </div>'''
    ),
    
    # Live Positions table
    (
        '''        <!-- LIVE POSITIONS -->
        <div class="g-card g-card-dark" style="border-color:rgba(240,183,47,0.35);">
            <div class="g-card-header d-flex justify-content-between align-items-center" style="padding:0.55rem 0.85rem;">
                <span style="color:var(--gold);font-weight:900;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.5px;">
                    <i class="fas fa-satellite me-1"></i> LIVE POSITIONS
                </span>
                <div class="d-flex align-items-center gap-2">
                    <span id="pos-count-badge" class="badge rounded-pill" style="background:rgba(240,183,47,0.15);color:var(--gold);border:1px solid rgba(240,183,47,0.3);font-size:0.62rem;">0</span>
                    <span id="total-pl-display" style="font-family:'JetBrains Mono';font-size:1rem;font-weight:900;color:var(--green);">+0.00</span>
                </div>
            </div>
            <div style="overflow-x:auto;overflow-y:auto;max-height:260px;-webkit-overflow-scrolling:touch;">
                <table class="pos-table" style="min-width:460px;">
                    <thead>
                        <tr>
                            <th class="ps-2">TYPE</th>
                            <th>SIZE</th>
                            <th>ENTRY</th>
                            <th>CURRENT (BROKER)</th>
                            <th>TARGET</th>
                            <th>STOP</th>
                            <th>P/L ($)</th>
                            <th class="pe-2">EDIT</th>
                        </tr>
                    </thead>
                    <tbody id="positions-list-body">
                        <tr><td colspan="8" class="text-center py-4" style="color:var(--text-lo);">No open positions</td></tr>
                    </tbody>
                </table>
            </div>
        </div>''',
        '''        <!-- LIVE POSITIONS -->
        <div class="g-card g-card-dark" style="border-color:rgba(240,183,47,0.35);">
            <div class="g-card-header d-flex justify-content-between align-items-center" style="padding:0.55rem 0.85rem;">
                <span style="color:var(--gold);font-weight:900;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.5px;">
                    <i class="fas fa-satellite me-1"></i> ออเดอร์ที่เปิดอยู่
                </span>
                <div class="d-flex align-items-center gap-2">
                    <span id="pos-count-badge" class="badge rounded-pill" style="background:rgba(240,183,47,0.15);color:var(--gold);border:1px solid rgba(240,183,47,0.3);font-size:0.62rem;">0</span>
                    <span id="total-pl-display" style="font-family:'JetBrains Mono';font-size:1rem;font-weight:900;color:var(--green);">+0.00</span>
                </div>
            </div>
            <div style="overflow-x:auto;overflow-y:auto;max-height:260px;-webkit-overflow-scrolling:touch;">
                <table class="pos-table" style="min-width:460px;">
                    <thead>
                        <tr>
                            <th class="ps-2">ประเภท</th>
                            <th>ขนาด</th>
                            <th>เปิด</th>
                            <th>ปัจจุบัน (BROKER)</th>
                            <th>TP</th>
                            <th>SL</th>
                            <th>กำไร ($)</th>
                            <th class="pe-2">แก้ไข</th>
                        </tr>
                    </thead>
                    <tbody id="positions-list-body">
                        <tr><td colspan="8" class="text-center py-4" style="color:var(--text-lo);">ไม่มีออเดอร์เปิดค้างอยู่</td></tr>
                    </tbody>
                </table>
            </div>
        </div>'''
    ),
    
    # Tactical Levels Card
    (
        '''        <!-- TACTICAL LEVELS -->
        <div class="g-card g-card-dark">
            <div class="g-card-header">
                <i class="fas fa-crosshairs" style="color:var(--red)"></i> TACTICAL LEVELS
            </div>
            <div class="p-2 pb-0">
                <div class="tactical-tabs mb-2">
                    <button class="t-tab sniper" onclick="setStrategy('SNIPER')" id="btn-strat-sniper">SNIPER</button>
                    <button class="t-tab scalper active" onclick="setStrategy('SCALPER')" id="btn-strat-scalper">SCALPER</button>
                    <button class="t-tab swing" onclick="setStrategy('SWING')" id="btn-strat-swing">SWING</button>
                    <button class="t-tab turtle" onclick="setStrategy('TURTLE')" id="btn-strat-turtle">TURTLE</button>
                </div>
                <div class="text-center mb-2">
                    <span id="strategy-label" class="badge" style="background:rgba(248,81,73,0.12);color:#f85149;font-weight:800;font-size:0.65rem;padding:3px 12px;border-radius:4px;border:1px solid rgba(248,81,73,0.3);">LEVERAGE 1:200 (SNIPER)</span>
                </div>
            </div>
            <div class="t-row"><span class="t-label">Breakout (Trigger)</span><span class="t-value" style="color:var(--red)" id="breakout-level-display">----.-</span></div>
            <div class="t-row"><span class="t-label" id="label-tactical-tp">Target (TP)</span><span class="t-value" style="color:var(--green)" id="tactical-tp">----.-</span></div>
            <div class="t-row"><span class="t-label" id="label-tactical-sl">Stop Loss (SL)</span><span class="t-value" style="color:var(--red)" id="tactical-sl">----.-</span></div>
            <div class="t-row"><span class="t-label">Volatility ATR(20)</span><span class="t-value" style="color:var(--gold)" id="live-n-val">-.--</span></div>''',
        '''        <!-- TACTICAL LEVELS -->
        <div class="g-card g-card-dark">
            <div class="g-card-header">
                <i class="fas fa-crosshairs" style="color:var(--red)"></i> ระดับราคาสำคัญ (TACTICAL LEVELS)
            </div>
            <div class="p-2 pb-0">
                <div class="tactical-tabs mb-2">
                    <button class="t-tab sniper" onclick="setStrategy('SNIPER')" id="btn-strat-sniper">สไนเปอร์</button>
                    <button class="t-tab scalper active" onclick="setStrategy('SCALPER')" id="btn-strat-scalper">สแคลเปอร์</button>
                    <button class="t-tab swing" onclick="setStrategy('SWING')" id="btn-strat-swing">สวิงเทรด</button>
                    <button class="t-tab turtle" onclick="setStrategy('TURTLE')" id="btn-strat-turtle">เทอร์เทิล</button>
                </div>
                <div class="text-center mb-2">
                    <span id="strategy-label" class="badge" style="background:rgba(248,81,73,0.12);color:#f85149;font-weight:800;font-size:0.65rem;padding:3px 12px;border-radius:4px;border:1px solid rgba(248,81,73,0.3);">LEVERAGE 1:200 (SNIPER)</span>
                </div>
            </div>
            <div class="t-row"><span class="t-label">จุดเกิดสัญญาณ (Breakout)</span><span class="t-value" style="color:var(--red)" id="breakout-level-display">----.-</span></div>
            <div class="t-row"><span class="t-label" id="label-tactical-tp">เป้าหมายทำกำไร (TP)</span><span class="t-value" style="color:var(--green)" id="tactical-tp">----.-</span></div>
            <div class="t-row"><span class="t-label" id="label-tactical-sl">จุดตัดขาดทุน (SL)</span><span class="t-value" style="color:var(--red)" id="tactical-sl">----.-</span></div>
            <div class="t-row"><span class="t-label">ความผันผวน ATR (20)</span><span class="t-value" style="color:var(--gold)" id="live-n-val">-.--</span></div>'''
    ),
    
    # Tactical Advisor and wait checklist
    (
        '''            <!-- TACTICAL ADVISOR -->
            <div id="tactical-advisor-box" class="m-2 p-3 rounded text-center" style="transition:all 0.3s;position:relative;overflow:hidden;">
                <div style="font-size:0.6rem;color:#475569;text-transform:uppercase;letter-spacing:2px;margin-bottom:4px;font-weight:800;">Tactical Advisor</div>
                <div id="tactical-advisor-text" class="fw-bold" style="font-size:1.05rem;color:var(--text-hi);letter-spacing:0.5px;font-weight:900;">Analyzing...</div>
                <div id="tactical-advisor-sub" style="font-size:0.68rem;color:#475569;margin-bottom:10px;font-weight:600;">Ready for execution</div>
                <div id="prox-radar-container" class="mt-2 p-2" style="display:none;background:rgba(0,0,0,0.3);border-radius:10px;border:1px solid var(--border);">
                    <div class="d-flex justify-content-between mb-2" style="font-size:0.72rem;font-weight:900;">
                        <span style="color:#1e40af;letter-spacing:0.5px;">DISTANCE TO BREAKOUT</span>
                        <span id="prox-radar-pts" style="color:#b45309;font-weight:900;">0.00 PTS</span>
                    </div>
                    <div class="progress" style="height:8px;background:rgba(255,255,255,0.08);border-radius:8px;overflow:visible;">
                        <div id="prox-radar-bar" class="progress-bar progress-bar-striped progress-bar-animated"
                             style="width:0%;border-radius:8px;background:var(--gold);"></div>
                    </div>
                    <div id="wait-checklist" class="mt-2 text-start" style="display:none;font-size:0.82rem;background:#f1f5f9;padding:12px;border-radius:8px;border:1px solid #cbd5e1;color:#0f172a;">
                        <div style="font-size:0.62rem;color:#334155;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;border-bottom:1px solid #cbd5e1;padding-bottom:4px;font-weight:900;">Entry Conditions</div>
                        <div class="mb-2 d-flex justify-content-between align-items-center">
                            <span style="color:#1e293b;font-weight:600;"><i id="cond-price-icon" class="fas fa-circle-notch fa-spin me-2" style="color:#64748b;"></i> Price Trigger</span>
                            <span id="cond-price-val" style="font-weight:800;color:#0f172a;">...</span>
                        </div>
                        <div class="mb-2 d-flex justify-content-between align-items-center">
                            <span style="color:#1e293b;font-weight:600;"><i id="cond-trend-icon" class="fas fa-circle-notch fa-spin me-2" style="color:#64748b;"></i> Trend Filter</span>
                            <span id="cond-trend-val" style="font-weight:800;color:#0f172a;">...</span>
                        </div>
                        <div class="d-flex justify-content-between align-items-center">
                            <span style="color:#1e293b;font-weight:600;"><i id="cond-mom-icon" class="fas fa-circle-notch fa-spin me-2" style="color:#64748b;"></i> Momentum (RSI)</span>
                            <span id="cond-mom-val" style="font-weight:800;color:#0f172a;">...</span>
                        </div>
                    </div>
                </div>
            </div>
            <div id="tactical-exit-advice" style="font-size:0.65rem;color:var(--text-lo);font-style:italic;padding:8px 12px;border-top:1px dashed var(--border);text-align:center;">
                Loading strategy advice...
            </div>''',
        '''            <!-- TACTICAL ADVISOR -->
            <div id="tactical-advisor-box" class="m-2 p-3 rounded text-center" style="transition:all 0.3s;position:relative;overflow:hidden;">
                <div style="font-size:0.6rem;color:#475569;text-transform:uppercase;letter-spacing:2px;margin-bottom:4px;font-weight:800;">ผู้ช่วยวิเคราะห์กลยุทธ์</div>
                <div id="tactical-advisor-text" class="fw-bold" style="font-size:1.05rem;color:var(--text-hi);letter-spacing:0.5px;font-weight:900;">กำลังวิเคราะห์...</div>
                <div id="tactical-advisor-sub" style="font-size:0.68rem;color:#475569;margin-bottom:10px;font-weight:600;">ระบบพร้อมส่งคำสั่ง</div>
                <div id="prox-radar-container" class="mt-2 p-2" style="display:none;background:rgba(0,0,0,0.3);border-radius:10px;border:1px solid var(--border);">
                    <div class="d-flex justify-content-between mb-2" style="font-size:0.72rem;font-weight:900;">
                        <span style="color:#1e40af;letter-spacing:0.5px;">ระยะห่างจากจุด BREAKOUT</span>
                        <span id="prox-radar-pts" style="color:#b45309;font-weight:900;">0.00 PTS</span>
                    </div>
                    <div class="progress" style="height:8px;background:rgba(255,255,255,0.08);border-radius:8px;overflow:visible;">
                        <div id="prox-radar-bar" class="progress-bar progress-bar-striped progress-bar-animated"
                             style="width:0%;border-radius:8px;background:var(--gold);"></div>
                    </div>
                    <div id="wait-checklist" class="mt-2 text-start" style="display:none;font-size:0.82rem;background:#f1f5f9;padding:12px;border-radius:8px;border:1px solid #cbd5e1;color:#0f172a;">
                        <div style="font-size:0.62rem;color:#334155;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;border-bottom:1px solid #cbd5e1;padding-bottom:4px;font-weight:900;">เงื่อนไขการเข้าซื้อขาย</div>
                        <div class="mb-2 d-flex justify-content-between align-items-center">
                            <span style="color:#1e293b;font-weight:600;"><i id="cond-price-icon" class="fas fa-circle-notch fa-spin me-2" style="color:#64748b;"></i> สัญญาณราคา (Price Trigger)</span>
                            <span id="cond-price-val" style="font-weight:800;color:#0f172a;">...</span>
                        </div>
                        <div class="mb-2 d-flex justify-content-between align-items-center">
                            <span style="color:#1e293b;font-weight:600;"><i id="cond-trend-icon" class="fas fa-circle-notch fa-spin me-2" style="color:#64748b;"></i> ตัวกรองแนวโน้ม (Trend Filter)</span>
                            <span id="cond-trend-val" style="font-weight:800;color:#0f172a;">...</span>
                        </div>
                        <div class="d-flex justify-content-between align-items-center">
                            <span style="color:#1e293b;font-weight:600;"><i id="cond-mom-icon" class="fas fa-circle-notch fa-spin me-2" style="color:#64748b;"></i> โมเมนตัม (RSI)</span>
                            <span id="cond-mom-val" style="font-weight:800;color:#0f172a;">...</span>
                        </div>
                    </div>
                </div>
            </div>
            <div id="tactical-exit-advice" style="font-size:0.65rem;color:var(--text-lo);font-style:italic;padding:8px 12px;border-top:1px dashed var(--border);text-align:center;">
                กำลังโหลดคำแนะนำกลยุทธ์...
            </div>'''
    ),
    
    # Smart Alerts (Corrected for exact text)
    (
        '''        <!-- SMART ALERTS -->
        <div class="alert-panel" id="alert-master-panel">
            <div class="alert-active-bg" id="alert-visual-signal"></div>
            <div class="d-flex justify-content-between align-items-center mb-2">
                <span class="matrix-label"><i class="fas fa-bell me-1" style="color:var(--gold)"></i> SMART ALERTS</span>
                <div class="d-flex align-items-center gap-2">
                    <span id="alert-status-text" style="font-size:0.6rem;color:var(--text-lo);">OFF</span>
                    <div class="form-check form-switch m-0">
                        <input class="form-check-input" type="checkbox" id="alert-master-toggle" style="cursor:pointer;" onchange="handleToggleChange()">
                    </div>
                </div>
            </div>
            <div class="mb-2">
                <label class="matrix-label d-block mb-1" style="font-size:0.58rem;text-align:center;">HIGH TARGET (TP)</label>
                <div class="d-flex gap-1 align-items-center">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('high',-10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">-10</button>
                    <input type="number" id="alert-high" class="alert-input flex-grow-1" placeholder="----.--" step="0.1">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('high',10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">+10</button>
                </div>
            </div>
            <div class="mb-2">
                <label class="matrix-label d-block mb-1" style="font-size:0.58rem;text-align:center;">LOW TARGET (SL)</label>
                <div class="d-flex gap-1 align-items-center">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('low',-10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">-10</button>
                    <input type="number" id="alert-low" class="alert-input flex-grow-1" placeholder="----.--" step="0.1">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('low',10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">+10</button>
                </div>
            </div>
            <div class="d-flex gap-2">
                <button class="btn btn-sm rounded-pill flex-grow-1 btn-test-sound" onclick="testAlertSound()" style="border:1px solid var(--border);font-size:0.62rem;">
                    <i class="fas fa-volume-up me-1"></i> Test
                </button>
                <button class="btn btn-sm rounded-pill flex-grow-1 btn-test-sound" onclick="syncAlertsToEntry()" style="border:1px solid rgba(88,166,255,0.3);color:var(--blue);font-size:0.62rem;">
                    <i class="fas fa-sync-alt me-1"></i> Sync ±20
                </button>
            </div>
            <div id="alert-sound-blocked" class="d-none mt-2 text-center">
                <span class="badge" style="background:rgba(240,183,47,0.15);color:var(--gold);border:1px solid rgba(240,183,47,0.3);font-size:0.62rem;padding:4px 8px;cursor:pointer;" onclick="alertSound.play()">
                    <i class="fas fa-volume-mute me-1"></i> SOUND BLOCKED — คลิกเพื่อเปิดเสียง
                </span>
            </div>
            <div id="alert-trigger-msg" class="mt-2 d-none">
                <div class="text-danger fw-bold text-center mb-2" style="font-size:0.78rem;animation:blink 0.5s infinite;">
                    <i class="fas fa-exclamation-triangle"></i> PRICE REACHED!
                </div>
                <button class="btn btn-danger w-100 fw-bold" onclick="silenceAlarm()" style="border-radius:8px;font-size:0.85rem;position:relative;z-index:9999;">
                    <i class="fas fa-volume-mute me-2"></i> STOP ALARM
                </button>
            </div>''',
        '''        <!-- SMART ALERTS -->
        <div class="alert-panel" id="alert-master-panel">
            <div class="alert-active-bg" id="alert-visual-signal"></div>
            <div class="d-flex justify-content-between align-items-center mb-2">
                <span class="matrix-label"><i class="fas fa-bell me-1" style="color:var(--gold)"></i> ระบบแจ้งเตือนอัจฉริยะ (SMART ALERTS)</span>
                <div class="d-flex align-items-center gap-2">
                    <span id="alert-status-text" style="font-size:0.6rem;color:var(--text-lo);">OFF</span>
                    <div class="form-check form-switch m-0">
                        <input class="form-check-input" type="checkbox" id="alert-master-toggle" style="cursor:pointer;" onchange="handleToggleChange()">
                    </div>
                </div>
            </div>
            <div class="mb-2">
                <label class="matrix-label d-block mb-1" style="font-size:0.58rem;text-align:center;">ราคาสูงสุดที่ตั้งเตือน (TP)</label>
                <div class="d-flex gap-1 align-items-center">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('high',-10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">-10</button>
                    <input type="number" id="alert-high" class="alert-input flex-grow-1" placeholder="----.--" step="0.1">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('high',10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">+10</button>
                </div>
            </div>
            <div class="mb-2">
                <label class="matrix-label d-block mb-1" style="font-size:0.58rem;text-align:center;">ราคาต่ำสุดที่ตั้งเตือน (SL)</label>
                <div class="d-flex gap-1 align-items-center">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('low',-10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">-10</button>
                    <input type="number" id="alert-low" class="alert-input flex-grow-1" placeholder="----.--" step="0.1">
                    <button class="btn btn-sm px-2" onclick="adjustAlert('low',10)" style="background:rgba(255,255,255,0.05);color:var(--text-lo);border:1px solid var(--border);border-radius:6px;font-size:0.7rem;">+10</button>
                </div>
            </div>
            <div class="d-flex gap-2">
                <button class="btn btn-sm rounded-pill flex-grow-1 btn-test-sound" onclick="testAlertSound()" style="border:1px solid var(--border);font-size:0.62rem;">
                    <i class="fas fa-volume-up me-1"></i> ทดสอบเสียง
                </button>
                <button class="btn btn-sm rounded-pill flex-grow-1 btn-test-sound" onclick="syncAlertsToEntry()" style="border:1px solid rgba(88,166,255,0.3);color:var(--blue);font-size:0.62rem;">
                    <i class="fas fa-sync-alt me-1"></i> ซิงก์ราคา ±20
                </button>
            </div>
            <div id="alert-sound-blocked" class="d-none mt-2 text-center">
                <span class="badge" style="background:rgba(240,183,47,0.15);color:var(--gold);border:1px solid rgba(240,183,47,0.3);font-size:0.62rem;padding:4px 8px;cursor:pointer;" onclick="alertSound.play()">
                    <i class="fas fa-volume-mute me-1"></i> SOUND BLOCKED — คลิกเพื่อเปิดเสียง
                </span>
            </div>
            <div id="alert-trigger-msg" class="mt-2 d-none">
                <div class="text-danger fw-bold text-center mb-2" style="font-size:0.78rem;animation:blink 0.5s infinite;">
                    <i class="fas fa-exclamation-triangle"></i> ราคาถึงเป้าหมายแล้ว!
                </div>
                <button class="btn btn-danger w-100 fw-bold" onclick="silenceAlarm()" style="border-radius:8px;font-size:0.85rem;position:relative;z-index:9999;">
                    <i class="fas fa-volume-mute me-2"></i> ปิดเสียงเตือน
                </button>
            </div>'''
    ),
    
    # Pullback Alert section
    (
        '''            <!-- Pullback Alert -->
            <div style="margin-top:0.7rem; border-top:1px solid var(--border); padding-top:0.6rem;">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span style="font-size:0.72rem; color:var(--text-hi); font-weight:700;">
                        <i class="fas fa-arrow-down me-1" style="color:var(--gold);"></i> PULLBACK ALERT
                    </span>
                    <div class="d-flex align-items-center gap-2">
                        <span id="pb-status" style="font-size:0.65rem; color:#94a3b8;">WATCHING</span>
                        <div class="form-check form-switch mb-0" style="transform:scale(0.8); transform-origin:right;">
                            <input class="form-check-input" type="checkbox" id="pullback-alert-toggle" style="cursor:pointer;"
                                onchange="localStorage.setItem('pb_alert_on', this.checked ? '1' : '0')">
                        </div>
                    </div>
                </div>
                <div class="d-flex align-items-center gap-2">
                    <span style="font-size:0.65rem; color:var(--text-lo); white-space:nowrap;">เตือนเมื่อห่าง ≤</span>
                    <input type="number" id="pullback-threshold" value="15" min="1" max="100" step="1"
                        style="width:55px; background:var(--bg-input); border:1px solid var(--border); border-radius:6px; color:var(--text-hi); font-size:0.75rem; padding:2px 6px; text-align:center;"
                        onchange="localStorage.setItem('pb_threshold', this.value)">
                    <span style="font-size:0.65rem; color:var(--text-lo);">pts จาก Breakout</span>
                </div>''',
        '''            <!-- Pullback Alert -->
            <div style="margin-top:0.7rem; border-top:1px solid var(--border); padding-top:0.6rem;">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span style="font-size:0.72rem; color:var(--text-hi); font-weight:700;">
                        <i class="fas fa-arrow-down me-1" style="color:var(--gold);"></i> แจ้งเตือนจุดย่อตัว (PULLBACK)
                    </span>
                    <div class="d-flex align-items-center gap-2">
                        <span id="pb-status" style="font-size:0.65rem; color:#94a3b8;">กำลังเฝ้าระวัง</span>
                        <div class="form-check form-switch mb-0" style="transform:scale(0.8); transform-origin:right;">
                            <input class="form-check-input" type="checkbox" id="pullback-alert-toggle" style="cursor:pointer;"
                                onchange="localStorage.setItem('pb_alert_on', this.checked ? '1' : '0')">
                        </div>
                    </div>
                </div>
                <div class="d-flex align-items-center gap-2">
                    <span style="font-size:0.65rem; color:var(--text-lo); white-space:nowrap;">เตือนเมื่อห่าง ≤</span>
                    <input type="number" id="pullback-threshold" value="15" min="1" max="100" step="1"
                        style="width:55px; background:var(--bg-input); border:1px solid var(--border); border-radius:6px; color:var(--text-hi); font-size:0.75rem; padding:2px 6px; text-align:center;"
                        onchange="localStorage.setItem('pb_threshold', this.value)">
                    <span style="font-size:0.65rem; color:var(--text-lo);">จุด (pts) จาก Breakout</span>
                </div>'''
    ),
    
    # Trade History card header & stats
    (
        '''            <div class="g-card">
                <div class="g-card-header d-flex justify-content-between align-items-center flex-wrap gap-2" style="padding: 0.7rem 1rem;">
                    <span style="color:var(--text-hi); font-weight: 800; font-size: 0.85rem;">
                        <i class="fas fa-history me-2" style="color:var(--gold)"></i> TRADE HISTORY
                    </span>
                    <div class="d-flex align-items-center gap-2">
                        <div class="btn-group btn-group-sm" role="group">
                            <button id="hist-btn-1d"  type="button" class="btn"  onclick="setHistRange('1d')"  style="font-size:0.72rem; border:1px solid var(--border); color:var(--text-hi); background:rgba(255,255,255,0.05);">1D</button>
                            <button id="hist-btn-7d"  type="button" class="btn"  onclick="setHistRange('7d')"  style="font-size:0.72rem; border:1px solid var(--border); color:var(--gold);   background:rgba(212,175,55,0.15);">7D</button>
                            <button id="hist-btn-30d" type="button" class="btn"  onclick="setHistRange('30d')" style="font-size:0.72rem; border:1px solid var(--border); color:var(--text-hi); background:rgba(255,255,255,0.05);">30D</button>
                            <button id="hist-btn-all" type="button" class="btn"  onclick="setHistRange('all')" style="font-size:0.72rem; border:1px solid var(--border); color:var(--text-hi); background:rgba(255,255,255,0.05);">ALL</button>
                        </div>
                        <button class="btn btn-sm rounded-pill px-3" onclick="updateTradeHistory()" style="font-size: 0.72rem; border: 1px solid var(--border); color: var(--text-hi); background: rgba(255,255,255,0.05);">
                            <i class="fas fa-sync-alt me-1"></i> Refresh
                        </button>
                    </div>
                </div>
                <!-- Stats Bar -->
                <div id="hist-stats-bar" style="display:flex; gap:1.5rem; padding:0.45rem 1rem; background:rgba(255,255,255,0.03); border-bottom:1px solid var(--border); font-size:0.75rem; flex-wrap:wrap;">
                    <span style="color:var(--text-lo);">Trades: <strong id="hs-total" style="color:var(--text-hi);">—</strong></span>
                    <span style="color:var(--text-lo);">Win Rate: <strong id="hs-wr" style="color:#22c55e;">—</strong></span>
                    <span style="color:var(--text-lo);">Net P/L: <strong id="hs-pl" style="color:var(--text-hi);">—</strong></span>
                    <span style="color:var(--text-lo);">Comm+Swap: <strong id="hs-fee" style="color:#f59e0b;">—</strong></span>
                    <span style="color:var(--text-lo);">Wins: <strong id="hs-wins" style="color:#22c55e;">—</strong></span>
                    <span style="color:var(--text-lo);">Losses: <strong id="hs-loss" style="color:#ef4444;">—</strong></span>
                </div>''',
        '''            <div class="g-card">
                <div class="g-card-header d-flex justify-content-between align-items-center flex-wrap gap-2" style="padding: 0.7rem 1rem;">
                    <span style="color:var(--text-hi); font-weight: 800; font-size: 0.85rem;">
                        <i class="fas fa-history me-2" style="color:var(--gold)"></i> ประวัติการเทรด (TRADE HISTORY)
                    </span>
                    <div class="d-flex align-items-center gap-2">
                        <div class="btn-group btn-group-sm" role="group">
                            <button id="hist-btn-1d"  type="button" class="btn"  onclick="setHistRange('1d')"  style="font-size:0.72rem; border:1px solid var(--border); color:var(--text-hi); background:rgba(255,255,255,0.05);">1D</button>
                            <button id="hist-btn-7d"  type="button" class="btn"  onclick="setHistRange('7d')"  style="font-size:0.72rem; border:1px solid var(--border); color:var(--gold);   background:rgba(212,175,55,0.15);">7D</button>
                            <button id="hist-btn-30d" type="button" class="btn"  onclick="setHistRange('30d')" style="font-size:0.72rem; border:1px solid var(--border); color:var(--text-hi); background:rgba(255,255,255,0.05);">30D</button>
                            <button id="hist-btn-all" type="button" class="btn"  onclick="setHistRange('all')" style="font-size:0.72rem; border:1px solid var(--border); color:var(--text-hi); background:rgba(255,255,255,0.05);">ALL</button>
                        </div>
                        <button class="btn btn-sm rounded-pill px-3" onclick="updateTradeHistory()" style="font-size: 0.72rem; border: 1px solid var(--border); color: var(--text-hi); background: rgba(255,255,255,0.05);">
                            <i class="fas fa-sync-alt me-1"></i> รีเฟรช
                        </button>
                    </div>
                </div>
                <!-- Stats Bar -->
                <div id="hist-stats-bar" style="display:flex; gap:1.5rem; padding:0.45rem 1rem; background:rgba(255,255,255,0.03); border-bottom:1px solid var(--border); font-size:0.75rem; flex-wrap:wrap;">
                    <span style="color:var(--text-lo);">จำนวนไม้: <strong id="hs-total" style="color:var(--text-hi);">—</strong></span>
                    <span style="color:var(--text-lo);">อัตราการชนะ (Win Rate): <strong id="hs-wr" style="color:#22c55e;">—</strong></span>
                    <span style="color:var(--text-lo);">กำไร/ขาดทุนสุทธิ: <strong id="hs-pl" style="color:var(--text-hi);">—</strong></span>
                    <span style="color:var(--text-lo);">ค่าธรรมเนียม/สวอป: <strong id="hs-fee" style="color:#f59e0b;">—</strong></span>
                    <span style="color:var(--text-lo);">ชนะ: <strong id="hs-wins" style="color:#22c55e;">—</strong></span>
                    <span style="color:var(--text-lo);">แพ้: <strong id="hs-loss" style="color:#ef4444;">—</strong></span>
                </div>'''
    ),
    
    # Trade History Table Header
    (
        '''                        <thead>
                            <tr>
                                <th class="ps-3" style="white-space:nowrap;">OPENED</th>
                                <th style="white-space:nowrap;">EXIT REASON</th>
                                <th>TYPE</th>
                                <th>LOTS</th>
                                <th>ENTRY</th>
                                <th>EXIT</th>
                                <th style="color:#ef4444;">SL SET</th>
                                <th title="Distance: exit price vs SL at close">DIST↔SL</th>
                                <th>PIPS</th>
                                <th>COMM+SWAP</th>
                                <th>NET P/L</th>
                                <th>R:R</th>
                                <th class="pe-3" style="white-space:nowrap;">CLOSED AT ▼</th>
                            </tr>
                        </thead>
                        <tbody id="trade-history-body">
                            <tr><td colspan="13" class="text-center py-5" style="color:var(--text-lo);">Loading trade history...</td></tr>
                        </tbody>''',
        '''                        <thead>
                            <tr>
                                <th class="ps-3" style="white-space:nowrap;">เวลาเปิด</th>
                                <th style="white-space:nowrap;">เหตุผลที่ปิด</th>
                                <th>ประเภท</th>
                                <th>ขนาด (Lots)</th>
                                <th>ราคาเข้า</th>
                                <th>ราคาปิด</th>
                                <th style="color:#ef4444;">SL ที่ตั้งไว้</th>
                                <th title="Distance: exit price vs SL at close">ระยะห่าง SL</th>
                                <th>Pips</th>
                                <th>ค่าธรรมเนียม</th>
                                <th>กำไร/ขาดทุน</th>
                                <th>R:R</th>
                                <th class="pe-3" style="white-space:nowrap;">เวลาปิด ▼</th>
                            </tr>
                        </thead>
                        <tbody id="trade-history-body">
                            <tr><td colspan="13" class="text-center py-5" style="color:var(--text-lo);">กำลังโหลดประวัติการเทรด...</td></tr>
                        </tbody>'''
    ),
    
    # Edit position modal body
    (
        '''            <div class="modal-body p-4">
                <input type="hidden" id="edit-pos-id">
                <div class="mb-3">
                    <label class="form-label text-success fw-bold" style="font-size:0.75rem;">TARGET (TP)</label>
                    <input type="number" id="edit-pos-tp" class="form-control text-center fw-bold"
                        style="background:#0f172a; color:#22c55e; border-color:#334155; font-family:'JetBrains Mono';"
                        step="0.1" placeholder="ราคา Take Profit">
                </div>
                <div class="mb-3">
                    <label class="form-label text-danger fw-bold" style="font-size:0.75rem;">STOP LOSS (SL)</label>
                    <input type="number" id="edit-pos-sl" class="form-control text-center fw-bold"
                        style="background:#0f172a; color:#ef4444; border-color:#334155; font-family:'JetBrains Mono';"
                        step="0.1" placeholder="ราคา Stop Loss">
                </div>''',
        '''            <div class="modal-body p-4">
                <input type="hidden" id="edit-pos-id">
                <div class="mb-3">
                    <label class="form-label text-success fw-bold" style="font-size:0.75rem;">เป้าหมายกำไร (TP PRICE)</label>
                    <input type="number" id="edit-pos-tp" class="form-control text-center fw-bold"
                        style="background:#0f172a; color:#22c55e; border-color:#334155; font-family:'JetBrains Mono';"
                        step="0.1" placeholder="ระบุราคาเป้าหมายกำไร">
                </div>
                <div class="mb-3">
                    <label class="form-label text-danger fw-bold" style="font-size:0.75rem;">ตัดขาดทุนอัตโนมัติ (SL PRICE)</label>
                    <input type="number" id="edit-pos-sl" class="form-control text-center fw-bold"
                        style="background:#0f172a; color:#ef4444; border-color:#334155; font-family:'JetBrains Mono';"
                        step="0.1" placeholder="ระบุราคาจุดยอมแพ้">
                </div>'''
    ),
    
    # Custom trade modal overlay at bottom
    (
        '''<!-- ══════ CUSTOM TRADE MODAL ══════ -->
<div class="trade-modal-overlay" id="trade-confirm-modal">
    <div class="trade-modal">
        <div class="tm-header">
            <div class="tm-title"><i class="fas fa-shield-alt me-2"></i>CONFIRM ORDER</div>
            <div style="font-size: 0.7rem; color: #64748b; text-transform: uppercase; margin-top: 5px;">Institutional Grade Execution</div>
        </div>
        <div class="tm-body">
            <div class="tm-row">
                <span class="tm-label">Strategy Mode</span>
                <span class="tm-value" id="tm-mode">SNIPER</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">Order Type</span>
                <span id="tm-type" class="tm-badge">BUY</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">Market Price</span>
                <span class="tm-value" id="tm-price" style="color:var(--gold);">$0.00</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">Position Size</span>
                <span class="tm-value" id="tm-lots">0.01 Lots</span>
            </div>
            <div class="tm-row" style="border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 10px;">
                <span class="tm-label">Take Profit</span>
                <span class="tm-value text-success" id="tm-tp">$0.00</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">Stop Loss</span>
                <span class="tm-value text-danger" id="tm-sl">$0.00</span>
            </div>

            <!-- Risk Auditor -->
            <div class="tm-risk-box" id="tm-risk-box">
                <div class="tm-risk-text" id="tm-risk-text">Warning message goes here...</div>
            </div>
        </div>
        <div class="tm-footer">
            <button class="btn-tm-cancel" id="btn-tm-cancel">CANCEL</button>
            <button class="btn-tm-confirm" id="btn-tm-confirm">CONFIRM LIVE ORDER</button>
        </div>
    </div>
</div>''',
        '''<!-- ══════ CUSTOM TRADE MODAL ══════ -->
<div class="trade-modal-overlay" id="trade-confirm-modal">
    <div class="trade-modal">
        <div class="tm-header">
            <div class="tm-title"><i class="fas fa-shield-alt me-2"></i> ยืนยันเปิดออเดอร์</div>
            <div style="font-size: 0.7rem; color: #64748b; text-transform: uppercase; margin-top: 5px;">การซื้อขายผ่านโบรกเกอร์ที่ได้รับการรับรองความปลอดภัย</div>
        </div>
        <div class="tm-body">
            <div class="tm-row">
                <span class="tm-label">ยุทธวิธีอ้างอิง</span>
                <span class="tm-value" id="tm-mode">SNIPER</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">ประเภทออเดอร์</span>
                <span id="tm-type" class="tm-badge">BUY</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">ราคาตลาดล่าสุด</span>
                <span class="tm-value" id="tm-price" style="color:var(--gold);">$0.00</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">ขนาดออเดอร์ (Lots)</span>
                <span class="tm-value" id="tm-lots">0.01 Lots</span>
            </div>
            <div class="tm-row" style="border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 10px;">
                <span class="tm-label">เป้าหมายกำไร (TP)</span>
                <span class="tm-value text-success" id="tm-tp">$0.00</span>
            </div>
            <div class="tm-row">
                <span class="tm-label">ตัดขาดทุน (SL)</span>
                <span class="tm-value text-danger" id="tm-sl">$0.00</span>
            </div>

            <!-- Risk Auditor -->
            <div class="tm-risk-box" id="tm-risk-box">
                <div class="tm-risk-text" id="tm-risk-text">ข้อมูลการตรวจสอบความเสี่ยงไม้...</div>
            </div>
        </div>
        <div class="tm-footer">
            <button class="btn-tm-cancel" id="btn-tm-cancel">ยกเลิก</button>
            <button class="btn-tm-confirm" id="btn-tm-confirm">ส่งคำสั่งเข้าพอร์ตจริง</button>
        </div>
    </div>
</div>'''
    ),
]

# Run precise block replacements first
for target, replacement in blocks:
    if target in content:
        content = content.replace(target, replacement)
        print(f"Replaced block successfully.")
    else:
        # Let's inspect the target to see why it skipped.
        # Check first line of target
        first_line = target.splitlines()[0] if '\n' in target else target
        print(f"Skipped block replacement starting with: {repr(first_line)}")
        sys.exit(1)

# Now run smaller exact string replaces on content that remains
specific_replaces = [
    # JS Strategy label text updates
    ("lbl.innerText = 'ULTRA-SHORT (SNIPER)';", "lbl.innerText = 'ยุทธวิธีระยะสั้นพิเศษ (SNIPER)';"),
    ("lbl.innerText = 'SHORT-TERM (SCALPER)';", "lbl.innerText = 'ยุทธวิธีระยะสั้น (SCALPER)';"),
    ("lbl.innerText = 'MEDIUM-TERM (SWING)';", "lbl.innerText = 'ยุทธวิธีระยะกลาง (SWING)';"),

    ("stratBadge.innerText = 'LEVERAGE 1:200 (SNIPER)';", "stratBadge.innerText = 'เลเวอเรจ 1:200 (SNIPER)';"),
    ("stratBadge.innerText = 'ULTRA-PRECISION (SCALPER)';", "stratBadge.innerText = 'ยุทธวิธีความแม่นยำสูง (SCALPER)';"),
    ("stratBadge.innerText = 'MEDIUM-TERM (SWING)';", "stratBadge.innerText = 'ยุทธวิธีระยะกลาง (SWING)';"),
    ("stratBadge.innerText = 'LONG-TERM (TURTLE)';", "stratBadge.innerText = 'ยุทธวิธีรันเทรนด์ยาว (TURTLE)';"),

    # JS Advisor text updates
    ("'AVOID: SUICIDE ZONE'", "'หลีกเลี่ยง: โซนอันตราย (SUICIDE ZONE)'"),
    ("'Price is beyond Safety Stop'", "'ราคาอยู่เกินจุดตัดขาดทุนเพื่อความปลอดภัย'"),
    ("'DANGEROUS: TIGHT SL'", "'อันตราย: จุดยอมแพ้แคบเกินไป (TIGHT SL)'"),
    ("'High risk of immediate stop-out'", "'มีความเสี่ยงสูงที่จะโดนสะบัดชนคัททันที'"),
    ("'CAUTION: WIDE SL'", "'ระวัง: จุดยอมแพ้กว้างเกินไป (WIDE SL)'"),
    ("'Capital at risk due to distance'", "'มีความเสี่ยงที่จะเสียเงินทุนปริมาณมากเนื่องจากระยะ SL ไกล'"),
    ("'EXCELLENT SETUP'", "'การตั้งค่าไม้ดีเยี่ยม (EXCELLENT)'"),
    ("`R:R is ${rr.toFixed(1)}x — Surgical Entry`", "`อัตราส่วน R:R อยู่ที่ ${rr.toFixed(1)}x — จุดเข้าเทรดสไนเปอร์`"),
    ("'STANDARD SETUP'", "'การตั้งค่าไม้ทั่วไป (STANDARD)'"),
    ("'Balanced risk profile'", "'สัดส่วนความเสี่ยงสมดุล'"),

    # JS Proximity radar & signals
    ("dist.toFixed(2) + ' PTS'", "dist.toFixed(2) + ' จุด (PTS)'"),
    ("signalSubtext.innerText = `Price in STOP ZONE ($${stopPrice.toFixed(2)}). DO NOT ENTRY.`;", "signalSubtext.innerText = `ราคาอยู่ในเขต Stop Zone ($${stopPrice.toFixed(2)}) ห้ามเปิดออเดอร์เด็ดขาด`;"),
    ("signalSubtext.innerText = `Price above ${breakoutPrice.toFixed(2)}. Consider LONG.`;", "signalSubtext.innerText = `ราคาอยู่เหนือ ${breakoutPrice.toFixed(2)} พิจารณาเปิดสถานะ BUY`;"),
    ("signalSubtext.innerText = `Price below ${breakoutPrice.toFixed(2)}. Consider SHORT.`;", "signalSubtext.innerText = `ราคาอยู่ต่ำกว่า ${breakoutPrice.toFixed(2)} พิจารณาเปิดสถานะ SELL`;"),
    ("signalSubtext.innerText = `Monitoring ${activeStrategy} at ${breakoutPrice.toFixed(2)}.`;", "signalSubtext.innerText = `กำลังเฝ้าสัญญาณ ${activeStrategy} ที่ระดับ ${breakoutPrice.toFixed(2)}`;"),
    ("proxPts.innerText = `${distToEntry.toFixed(2)} PTS REMAINING`;", "proxPts.innerText = `${distToEntry.toFixed(2)} จุด (PTS) ที่เหลือ`;"),

    # JS checklist values
    ("pVal.innerText = priceOk ? 'READY' : (lastPrice < breakoutPrice ? 'BELOW' : 'READY');", "pVal.innerText = priceOk ? 'พร้อม' : (lastPrice < breakoutPrice ? 'ต่ำกว่า' : 'พร้อม');"),
    ("tVal.innerText = trendOk ? 'BULLISH' : 'BEARISH';", "tVal.innerText = trendOk ? 'ขาขึ้น (BULLISH)' : 'ขาลง (BEARISH)';"),
    ("'STRIKE ZONE!'", "'โซนเริ่มเทรด (STRIKE ZONE)!'"),
    ("'Price is approaching trigger level.'", "'ราคากำลังเข้าใกล้ระดับสัญญาณเข้าซื้อ'"),

    # JS Status & Decision center
    ("'CRITICAL RISK!'", "'ความเสี่ยงวิกฤต (CRITICAL)!'"),
    ("'BUY SIGNAL!'", "'สัญญาณเข้าซื้อ (BUY)!'"),
    ("'SELL SIGNAL!'", "'สัญญาณเข้าขาย (SELL)!'"),
    ("'WAITING...'", "'กำลังรอสัญญาณ...'"),

    # JS alert logs & messages
    ("`🚨 SAFETY LIMIT: Cannot exceed 0.05 Lots. Adjusted to 0.05.`", "`🚨 ข้อจำกัดความปลอดภัย: ไม่สามารถเปิดไม้เกิน 0.05 Lots ระบบได้ปรับเป็น 0.05 ให้แล้ว`"),
    ("`REQUEST: ${type} ${lotSize} Lots`", "`ขอเปิดออเดอร์: ${type} ${lotSize} Lots`"),
    ("'All positions closed'", "'ปิดสถานะออเดอร์ทั้งหมดเรียบร้อยแล้ว'"),
    ("'Close failed: ' + d.error", "'ปิดออเดอร์ไม่สำเร็จ: ' + d.error"),
    ("No trades found for this period", "ไม่พบประวัติการเทรดในช่วงเวลานี้"),
    ("Error loading history", "เกิดข้อผิดพลาดในการโหลดประวัติ"),
    ("No open positions", "ไม่มีออเดอร์เปิดค้างอยู่"),
    ('addFeedMessage("Alerts synced to Entry ±$20");', 'addFeedMessage("ซิงก์ระดับราคาตั้งเตือนเรียบร้อยแล้ว (อ้างอิงราคาเปิด ±$20)");'),
    ("No active positions found to sync with.", "ไม่พบสถานะออเดอร์ที่เปิดอยู่เพื่อทำการซิงก์"),
    ("if (!confirm('Close all positions?')) return;", "if (!confirm('ยืนยันการปิดสถานะทั้งหมด?')) return;"),
    ("Failed to start AI", "เริ่มการทำงาน AI ล้มเหลว"),
    ("GOLD AI STRATEGIST", "GOLD AI STRATEGIST (วิเคราะห์ราคาทองคำ)"),
    (">Close</button>", ">ปิดหน้าต่าง</button>"),
    ("Alarm Silenced & Monitoring Disabled.", "ปิดเสียงเตือนและระบบเฝ้าระวังชั่วคราว"),

    # JS confirm trade modal details
    ("'Test Order'", "'คำสั่งทดสอบ'"),
    ("'Manual'", "'สั่งการเอง'"),
    ("SUCCESS: Order", "ส่งคำสั่งสำเร็จ: ออเดอร์"),
    ("FAILED:", "ส่งคำสั่งล้มเหลว:"),
    ("ERROR: Connection failure.", "ข้อผิดพลาด: การเชื่อมต่อระบบขัดข้อง"),

    # Time display
    ("Updated: ' + now.toTimeString().slice(0,8)", "อัปเดตเมื่อ: ' + now.toTimeString().slice(0,8)"),
    ("Updated: ' + new Date().toTimeString().slice(0,8)", "อัปเดตเมื่อ: ' + new Date().toTimeString().slice(0,8)"),

]

for target, replacement in specific_replaces:
    if target in content:
        content = content.replace(target, replacement)
        print(f"Replaced: {repr(target)[:50]}...")
    else:
        print(f"Skipped specific replacement for: {repr(target)}")
        sys.exit(1)

# Save the translated file
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Translation execution finished successfully.")
