from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, date
import calendar
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from models import Session, Labour, DailyEntry, get_mirrored_shift, engine

app = Flask(__name__)
app.secret_key = "factory_fix_v24"

ADMIN_PASSWORD = "admin" 

# NEW FEATURE SAFETY: Auto-add columns to existing DB safely
with engine.connect() as conn:
    try: conn.execute(text("ALTER TABLE labours ADD COLUMN wage_rate INTEGER DEFAULT 0")); conn.commit()
    except: pass
    try: conn.execute(text("ALTER TABLE labours ADD COLUMN last_increment_month TEXT DEFAULT ''")); conn.commit()
    except: pass
    try: conn.execute(text("ALTER TABLE labours ADD COLUMN is_active INTEGER DEFAULT 1")); conn.commit()
    except: pass

@app.route('/')
def index():
    s = Session()
    # ONLY load workers where is_active is 1
    labours = s.query(Labour).filter_by(is_active=1).all()
    current_m_y = datetime.now().strftime("%m-%Y")
    s.close()
    return render_template('index.html', labours=labours, current_m_y=current_m_y)

@app.route('/notebook/<int:lid>')
def notebook(lid):
    s = Session()
    labour = s.query(Labour).get(lid)
    if not labour: return redirect('/')
    
    now = datetime.now()
    m_y = request.args.get('m', now.strftime("%m-%Y"))
    req_month, req_year = map(int, m_y.split('-'))
    
    is_current_month = (m_y == now.strftime("%m-%Y"))
    if is_current_month: current_day = now.day 
    else: current_day = 32 if date(req_year, req_month, 1) < now.date() else 0
    
    days_count = calendar.monthrange(req_year, req_month)[1]
    
    for d in range(1, days_count + 1):
        exists = s.query(DailyEntry).filter_by(labour_id=lid, day_number=d, month_year=m_y).first()
        if not exists:
            s.add(DailyEntry(labour_id=lid, day_number=d, day_name=date(req_year, req_month, d).strftime("%a"), 
                             month_year=m_y, shift=get_mirrored_shift(labour.group, d, m_y), mc_no=labour.home_mc))
        elif exists.manual_shift == 0:
            exists.shift = get_mirrored_shift(labour.group, d, m_y)
    s.commit()
    
    entries = s.query(DailyEntry).filter_by(labour_id=lid, month_year=m_y).order_by(DailyEntry.day_number).all()
    
    available_months = [e[0] for e in s.query(DailyEntry.month_year).filter_by(labour_id=lid).distinct().all()]
    if m_y not in available_months: available_months.append(m_y)
    available_months.sort(key=lambda x: datetime.strptime(x, "%m-%Y"), reverse=True)
    
    s.close()
    return render_template('notebook.html', labour=labour, entries=entries, now_day=current_day, available_months=available_months, current_m_y=m_y)

@app.route('/update/<int:eid>', methods=['POST'])
def update(eid):
    s = Session()
    try:
        e = s.query(DailyEntry).get(eid)
        if e is None: return redirect('/')
        lab = s.query(Labour).get(e.labour_id)
        
        if request.form['shift'] != e.shift: e.manual_shift = 1
        e.shift, e.mc_no = request.form['shift'], request.form['mc']
        e.stitch = int(request.form['stitch'] or 0)
        e.advance = int(request.form['adv'] or 0)
        e.hours = request.form['hours']
        s.commit() 

        now_day = datetime.now().day
        is_current_month = (e.month_year == datetime.now().strftime("%m-%Y"))
        check_day = now_day if is_current_month else 32

        all_entries = s.query(DailyEntry).filter_by(labour_id=lab.id, month_year=e.month_year).order_by(DailyEntry.day_number).all()

        running_duty_count = 0
        for entry in all_entries:
            if entry.stitch > 0 and entry.shift != "CHANGE":
                running_duty_count += 1
                entry.duty = str(running_duty_count)
            else:
                if entry.day_number <= check_day: entry.duty = "X" 
                else: entry.duty = ""  
        
        s.commit() 
        flash(f"Updated: {lab.name}")
        
    finally: s.close()
    return redirect(url_for('notebook', lid=e.labour_id, m=e.month_year))

@app.route('/add_labour', methods=['POST'])
def add_labour():
    s = Session()
    try:
        wage = int(request.form.get('wage', 0) or 0) 
        # First check if worker exists but is archived
        existing = s.query(Labour).filter_by(name=request.form['name'].upper()).first()
        if existing:
            if existing.is_active == 0:
                flash(f"⚠️ {existing.name} is in the Archive! Please restore them from the Archive page.")
            else:
                flash(f"⚠️ Worker {existing.name} already exists!")
            return redirect('/')

        s.add(Labour(name=request.form['name'].upper(), group=request.form['group'], home_mc=request.form['mc'], wage_rate=wage))
        s.commit()
        flash(f"Added worker: {request.form['name'].upper()}")
    except IntegrityError:
        s.rollback()
        flash(f"Error: Database constraint failed.")
    finally: s.close()
    return redirect('/')

# UPDATE: Turn Delete into Archive (Preserves records)
@app.route('/delete_labour/<int:lid>', methods=['POST'])
def delete_labour(lid):
    s = Session()
    try:
        password = request.form.get('password')
        if password != ADMIN_PASSWORD:
            flash("❌ Incorrect Admin Password! Action cancelled.")
            return redirect('/')
            
        lab = s.query(Labour).get(lid)
        if lab:
            lab.is_active = 0 # Simply hide them, DO NOT delete records
            s.commit()
            flash(f"📦 Archived {lab.name} to preserve records.")
    finally: s.close()
    return redirect('/')

@app.route('/bulk_print')
def bulk_print():
    s = Session()
    now = datetime.now()
    m_y = request.args.get('m', now.strftime("%m-%Y"))
    req_month, req_year = map(int, m_y.split('-'))
    
    # ONLY print active workers
    labours = s.query(Labour).filter_by(is_active=1).order_by(Labour.group, Labour.name).all()
    all_data = []
    
    for labour in labours:
        days_count = calendar.monthrange(req_year, req_month)[1]
        for d in range(1, days_count + 1):
            exists = s.query(DailyEntry).filter_by(labour_id=labour.id, day_number=d, month_year=m_y).first()
            if not exists:
                s.add(DailyEntry(labour_id=labour.id, day_number=d, day_name=date(req_year, req_month, d).strftime("%a"), 
                                 month_year=m_y, shift=get_mirrored_shift(labour.group, d, m_y), mc_no=labour.home_mc))
        s.commit()
        entries = s.query(DailyEntry).filter_by(labour_id=labour.id, month_year=m_y).order_by(DailyEntry.day_number).all()
        all_data.append({'labour': labour, 'entries': entries})
        
    s.close()
    return render_template('bulk_print.html', all_data=all_data, m_y=m_y)

@app.route('/update_wage/<int:lid>', methods=['POST'])
def update_wage(lid):
    s = Session()
    try:
        lab = s.query(Labour).get(lid)
        if lab and lab.wage_rate == 0:  
            lab.wage_rate = int(request.form.get('wage', 0))
            s.commit()
            flash(f"Initial Wage Locked for {lab.name}")
    finally: s.close()
    return redirect('/')

@app.route('/increment_wage/<int:lid>', methods=['POST'])
def increment_wage(lid):
    s = Session()
    try:
        password = request.form.get('password')
        added_amount = int(request.form.get('add_wage', 0))
        
        if password != ADMIN_PASSWORD:
            flash("❌ Incorrect Admin Password!")
            return redirect('/')
            
        lab = s.query(Labour).get(lid)
        current_month = datetime.now().strftime("%m-%Y")
        
        if lab and lab.last_increment_month != current_month:
            lab.wage_rate += added_amount
            lab.last_increment_month = current_month
            s.commit()
            flash(f"✅ Incremented wage for {lab.name}. New Wage: ₹{lab.wage_rate}")
        else:
            flash(f"⚠️ {lab.name} already received an increment this month!")
    finally: s.close()
    return redirect('/')

# NEW ROUTE: View Archived Workers
@app.route('/archive')
def archive():
    s = Session()
    archived_labours = s.query(Labour).filter_by(is_active=0).all()
    s.close()
    return render_template('archive.html', labours=archived_labours)

# NEW ROUTE: Restore Worker from Archive
@app.route('/restore_labour/<int:lid>', methods=['POST'])
def restore_labour(lid):
    s = Session()
    try:
        password = request.form.get('password')
        if password != ADMIN_PASSWORD:
            flash("❌ Incorrect Admin Password! Restore cancelled.")
            return redirect('/archive')
            
        lab = s.query(Labour).get(lid)
        if lab:
            lab.is_active = 1
            s.commit()
            flash(f"✅ Restored {lab.name} back to Active Duty.")
    finally: s.close()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)