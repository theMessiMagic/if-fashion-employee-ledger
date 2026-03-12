from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, date
import calendar
from models import Session, Labour, DailyEntry, get_mirrored_shift

app = Flask(__name__)
app.secret_key = "factory_fix_v24"

@app.route('/')
def index():
    s = Session()
    labours = s.query(Labour).all()
    s.close()
    return render_template('index.html', labours=labours)

@app.route('/notebook/<int:lid>')
def notebook(lid):
    s = Session()
    labour = s.query(Labour).get(lid)
    if not labour: return redirect('/')
    
    now = datetime.now()
    m_y = now.strftime("%m-%Y")
    current_day = now.day # This is the "today" marker
    
    days_count = calendar.monthrange(now.year, now.month)[1]
    
    # 1. Automatic Entry Creation (Same as before)
    for d in range(1, days_count + 1):
        exists = s.query(DailyEntry).filter_by(labour_id=lid, day_number=d, month_year=m_y).first()
        if not exists:
            s.add(DailyEntry(labour_id=lid, day_number=d, day_name=date(now.year, now.month, d).strftime("%a"), 
                             month_year=m_y, shift=get_mirrored_shift(labour.group, d, m_y), mc_no=labour.home_mc))
        elif exists.manual_shift == 0:
            exists.shift = get_mirrored_shift(labour.group, d, m_y)
    s.commit()
    
    # 2. Fetch all entries for the page
    entries = s.query(DailyEntry).filter_by(labour_id=lid, month_year=m_y).order_by(DailyEntry.day_number).all()
    s.close()
    
    # 3. IMPORTANT: Pass 'now_day' so the HTML knows where to show the EDIT button
    return render_template('notebook.html', labour=labour, entries=entries, now_day=current_day)

@app.route('/update/<int:eid>', methods=['POST'])
def update(eid):
    s = Session()
    try:
        e = s.query(DailyEntry).get(eid)
        if e is None: return redirect('/')
        lab = s.query(Labour).get(e.labour_id)
        
        # 1. Save the data you just typed
        if request.form['shift'] != e.shift: e.manual_shift = 1
        e.shift, e.mc_no = request.form['shift'], request.form['mc']
        e.stitch = int(request.form['stitch'] or 0)
        e.advance = int(request.form['adv'] or 0)
        e.hours = request.form['hours']
        s.commit() 

        # 2. Get all entries for the worker THIS month
        now_day = datetime.now().day
        all_entries = s.query(DailyEntry).filter_by(
            labour_id=lab.id, 
            month_year=e.month_year
        ).order_by(DailyEntry.day_number).all()

        # 3. The "Auto-Push" Brain
        running_duty_count = 0
        for entry in all_entries:
            # RULE: If there are stitches, it's a duty (unless it's a 'CHANGE' shift)
            if entry.stitch > 0 and entry.shift != "CHANGE":
                running_duty_count += 1
                entry.duty = str(running_duty_count)
            else:
                # If no stitches, check if the day has already passed
                if entry.day_number <= now_day:
                    entry.duty = "X" # Past/Today empty = Absent
                else:
                    entry.duty = ""  # Future empty = Blank
        
        s.commit() 
        flash(f"Updated: {lab.name}")
        
    finally: s.close()
    return redirect(url_for('notebook', lid=e.labour_id))
@app.route('/add_labour', methods=['POST'])
def add_labour():
    s = Session()
    try:
        s.add(Labour(name=request.form['name'].upper(), group=request.form['group'], home_mc=request.form['mc']))
        s.commit()
    finally: s.close()
    return redirect('/')

@app.route('/delete_labour/<int:lid>')
def delete_labour(lid):
    s = Session()
    try:
        s.query(DailyEntry).filter_by(labour_id=lid).delete()
        lab = s.query(Labour).get(lid); s.delete(lab); s.commit()
    finally: s.close()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)