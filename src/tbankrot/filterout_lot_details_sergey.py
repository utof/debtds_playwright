import json
from datetime import datetime, timedelta


def parse_date(date_str: str) -> datetime | None:
    """Parse date string in DD.MM.YYYY format or return None if empty."""
    if not date_str or date_str.strip() == "":
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d.%m.%Y")
    except ValueError:
        return None

def filter_lot_details():
    input_file = "debug/lot_details.json"
    output_file = "debug/lot_details_filtered.json"
    
    # Get current date (today)
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    future_14_days = today + timedelta(days=14)
    
    print("Filtering with criteria:")
    print(f"- Today: {today}")
    print(f"- Tomorrow: {tomorrow}")
    print(f"- 14+ days from now: {future_14_days}")
    
    try:
        # Read the JSON file
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Filter items
        filtered_items = []
        removed_count = 0
        keep_reasons = []
        remove_reasons = []
        
        for item in data.get('items', []):
            data_section = item.get('data', {})
            app_end_date_str = data_section.get('application_end_date', '')
            auction_end_date_str = data_section.get('auction_end_date', '')
            
            app_end_date = parse_date(app_end_date_str)
            auction_end_date = parse_date(auction_end_date_str)
            
            # Keep if application end date is before tomorrow OR empty
            app_end_condition = app_end_date is None or app_end_date.date() < tomorrow
            
            # Keep if auction end date is 14+ days in future OR empty
            auction_end_condition = auction_end_date is None or auction_end_date.date() > future_14_days
            
            if app_end_condition and auction_end_condition:
                filtered_items.append(item)
                keep_reasons.append(f"App end: {app_end_date_str} | Auction end: {auction_end_date_str}")
            else:
                removed_count += 1
                if not app_end_condition:
                    remove_reasons.append(f"App end too late: {app_end_date_str}")
                if not auction_end_condition:
                    remove_reasons.append(f"Auction end too soon: {auction_end_date_str}")
        
        # Update the data with filtered items
        data['items'] = filtered_items
        data['count'] = len(filtered_items)
        
        # Write filtered data to new file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("\nFiltering complete:")
        print(f"Original items: {len(data.get('items', []))}")
        print(f"Removed: {removed_count}")
        print(f"Remaining: {len(filtered_items)}")
        print(f"\nOutput saved to: {output_file}")
        
        if keep_reasons:
            print(f"\nSample kept items ({min(3, len(keep_reasons))}):")
            for reason in keep_reasons[:3]:
                print(f"  - {reason}")
        
        if remove_reasons:
            print(f"\nSample removed items ({min(3, len(remove_reasons))}):")
            for reason in remove_reasons[:3]:
                print(f"  - {reason}")
        
    except FileNotFoundError:
        print(f"Error: File {input_file} not found")
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in the file")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    filter_lot_details()
