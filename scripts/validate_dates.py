import csv
import sys
import os
from datetime import datetime

# Configure input file
CSV_FILE = "Data.csv"

def parse_date(date_str):
    if not date_str or date_str.strip() == "":
        return None
    
    # Try multiple formats found in CSV
    formats = [
        "%d/%m/%Y %H:%M",  # 16/01/2025 17:43
        "%d/%m/%Y"         # 24/01/2025
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None

def analyze_dates():
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} not found.")
        return

    print(f"Analyzing dates in {CSV_FILE}...\n")
    
    incoherent_count = 0
    total_rows = 0
    
    report_lines = []
    
    with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            total_rows += 1
            op_id = row.get("ID", "Unknown")
            project = row.get("nameProyect", "Unknown")
            
            # Parse Dates
            created_at = parse_date(row.get("Created"))
            deadline = parse_date(row.get("deadLine"))
            new_deadline = parse_date(row.get("newDeadLine"))
            delivery_date = parse_date(row.get("fechaEntregada"))
            
            issues = []
            
            if not created_at:
                issues.append("Missing creation date")
            else:
                # Logic Validations
                if delivery_date and delivery_date < created_at:
                    issues.append(f"Delivery ({delivery_date.date()}) BEFORE Creation ({created_at.date()})")
                
                if deadline and deadline < created_at:
                    # Ignore if the difference is just time on same day, check only dates
                    if deadline.date() < created_at.date():
                        issues.append(f"Deadline ({deadline.date()}) BEFORE Creation ({created_at.date()})")
                        
                if new_deadline and new_deadline < created_at:
                     if new_deadline.date() < created_at.date():
                        issues.append(f"New Deadline ({new_deadline.date()}) BEFORE Creation ({created_at.date()})")

            if issues:
                incoherent_count += 1
                report_lines.append(f"ID {op_id} - {project}: {', '.join(issues)}")

    # Summary
    print(f"Total Records: {total_rows}")
    print(f"Incoherent Records: {incoherent_count}")
    print("-" * 40)
    
    if report_lines:
        print("Issues Found:")
        for line in report_lines[:20]: # Show top 20
            print(line)
        if len(report_lines) > 20:
            print(f"... and {len(report_lines) - 20} more.")
    else:
        print("✅ No date inconsistencies found.")

if __name__ == "__main__":
    analyze_dates()
