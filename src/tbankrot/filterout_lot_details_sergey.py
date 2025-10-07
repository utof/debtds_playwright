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

    print(f"Filtering with criteria (today: {today}):")
    print(f"- REMOVE if application_end_date < {tomorrow} (too soon)")
    print(f"- KEEP if application_end_date empty OR >= {tomorrow} (enough time)")
    print(f"- REMOVE if auction_end_date <= {future_14_days} (too soon)")
    print(f"- KEEP if auction_end_date empty OR > {future_14_days} (enough time)")

    try:
        # Read the JSON file
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        original_count = len(data.get("items", []))
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

            # Application end date logic: KEEP if empty OR >= tomorrow
            app_end_keep = app_end_date is None or app_end_date.date() >= tomorrow

            # Auction end date logic: KEEP if empty OR > 14 days from now
            auction_end_keep = (
                auction_end_date is None or auction_end_date.date() > future_14_days
            )

            # Keep if BOTH conditions are true (both dates have enough time)
            if app_end_keep and auction_end_keep:
                filtered_items.append(item)
                if app_end_date is None and auction_end_date is None:
                    keep_reasons.append(
                        f"BOTH empty: App={app_end_date_str} | Auction={auction_end_date_str}"
                    )
                elif app_end_date is None:
                    keep_reasons.append(
                        f"App empty, Auction late: {auction_end_date_str}"
                    )
                elif auction_end_date is None:
                    keep_reasons.append(f"App late, Auction empty: {app_end_date_str}")
                else:
                    keep_reasons.append(
                        f"BOTH late: App={app_end_date_str} | Auction={auction_end_date_str}"
                    )
            else:
                # Remove if EITHER condition fails
                removed_count += 1
                if not app_end_keep:
                    remove_reasons.append(f"App too soon: {app_end_date_str}")
                if not auction_end_keep:
                    remove_reasons.append(f"Auction too soon: {auction_end_date_str}")
                if not app_end_keep and not auction_end_keep:
                    remove_reasons[-1] = (
                        f"BOTH too soon: App={app_end_date_str} | Auction={auction_end_date_str}"
                    )

        # Update the data with filtered items
        data["items"] = filtered_items
        data["count"] = len(filtered_items)

        # Write filtered data to new file
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print("\nFiltering complete:")
        print(f"Original items: {original_count}")
        print(f"Removed: {removed_count} (not enough time)")
        print(f"Remaining: {len(filtered_items)} (enough time)")
        print(f"Output saved to: {output_file}")

        # Test with your example
        print("\nYour example test (App end: 19.11.2025, Auction end: 19.11.2025):")
        app_test = parse_date("19.11.2025")
        auction_test = parse_date("19.11.2025")
        app_test_keep = app_test is None or app_test.date() >= tomorrow
        auction_test_keep = auction_test is None or auction_test.date() > future_14_days
        print(f"App end >= tomorrow: {app_test_keep} (19.11.2025 >= 2025-10-08)")
        print(f"Auction end > 14 days: {auction_test_keep} (19.11.2025 > 2025-10-21)")
        print(
            f"Result: {'KEEP' if app_test_keep and auction_test_keep else 'REMOVE'} ✓"
        )
        
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
