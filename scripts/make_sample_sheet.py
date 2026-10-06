"""Builds sample/sample_attendance.xlsx with FAKE names, laid out like the real
company attendance tab (role column, section headers, free-text answers)."""
from openpyxl import Workbook
from openpyxl.styles import Font

HEADER = ["", "Rank", "Last Name", "First Name", "Monday", "Tuesday", "Wednesday",
          "Thursday", "Friday", "Corps Lab", "Song of the Week"]
ROWS = [
    ["Freshman Platoon"],
    ["PL",  "C/2LT", "Park",   "Alex",   "Yes", "Yes", "Yes", "Yes", "Yes", "No, dentist appt.", ""],
    ["PSG", "C/SFC", "Nguyen", "Sam",    "No, army form cut", "yes", "yes", "yes", "yes", "yes", ""],
    ["SL",  "C/SSG", "Reed",   "Jordan", "yes", "yes", "yes", "yes", "No, Raider PT", "yes", ""],
    ["",    "NC/",   "Cole",   "Taylor", "Yes", "Yes", "", "Yes", "Yes", "Yes", ""],          # one blank
    ["",    "NC/",   "Diaz",   "Morgan", "", "", "", "", "", "", ""],                         # nothing filled
    ["",    "NC/",   "Hart",   "Casey",  "yes", "yes", "yes", "no, SIQ", "yes", "late, class", ""],
    ["SL",  "C/SSG", "Wells",  "Riley",  "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", ""],
    ["",    "NC/",   "Moss",   "Avery",  "like drew", "like drew", "like drew", "like drew", "like drew", "like drew", ""],
    ["",    "NC/",   "Fox",    "Jamie",  "Yes", "Yes", "Yes", "Yes", "Yes", "", ""],          # blank Corps Lab
    ["",    "NC/",   "Lane",   "Drew",   "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", ""],
]

wb = Workbook()
ws = wb.active
ws.title = "Attendance"
ws.append(["India Company — SAMPLE DATA (fake names). Blank cell = no response."])
ws.append(HEADER)
for r in ROWS:
    ws.append(r)
for row in ws.iter_rows():
    for c in row:
        c.font = Font(name="Arial", bold=c.row <= 2)
wb.save("sample/sample_attendance.xlsx")
print("wrote sample/sample_attendance.xlsx")
