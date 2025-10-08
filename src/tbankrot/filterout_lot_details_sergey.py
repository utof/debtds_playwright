import json
from datetime import datetime, timedelta
from typing import Any, Dict

# Global filtering flags for INN validation
REMOVE_EMPTY_INN = True  # Set to False to keep items with empty bankrupt_inn
REMOVE_INVALID_INN_LENGTH = (
    True  # Set to False to keep items with INN not 9 or 10 digits
)


def parse_date(date_str: str) -> datetime | None:
    """Parse date string in DD.MM.YYYY format or return None if empty."""
    if not date_str or date_str.strip() == "":
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d.%m.%Y")
    except ValueError:
        return None

def validate_inn(inn: str) -> bool:
    """Validate INN: must be 9 or 10 digits, not empty."""
    if not inn or inn.strip() == "":
        return False
    # Remove any non-digit characters and check length
    digits_only = "".join(filter(str.isdigit, inn.strip()))
    return len(digits_only) in (9, 10)


def filter_lot_details():
    input_file = "debug/lot_details.json"
    output_file = "debug/lot_details_filtered_without_invalid_inn.json"
    
    # Get current date (today)
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    future_14_days = today + timedelta(days=14)

    print(f"Filtering with criteria (today: {today}):")
    print(f"- REMOVE if application_end_date < {tomorrow} (too soon)")
    print(f"- KEEP if application_end_date empty OR >= {tomorrow} (enough time)")
    print(f"- REMOVE if auction_end_date <= {future_14_days} (too soon)")
    print(f"- KEEP if auction_end_date empty OR > {future_14_days} (enough time)")
    print(f"- REMOVE empty INN: {REMOVE_EMPTY_INN}")
    print(f"- REMOVE invalid INN length: {REMOVE_INVALID_INN_LENGTH}")

    try:
        # Read the JSON file
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        original_count = len(data.get("items", []))
        filtered_items = []
        removed_count = 0
        keep_reasons = []
        remove_reasons = []
        inn_empty_count = 0
        inn_invalid_count = 0
        
        for item in data.get('items', []):
            data_section = item.get('data', {})
            app_end_date_str = data_section.get('application_end_date', '')
            auction_end_date_str = data_section.get('auction_end_date', '')
            bankrupt_inn = data_section.get("bankrupt_inn", "")
            
            app_end_date = parse_date(app_end_date_str)
            auction_end_date = parse_date(auction_end_date_str)

            # Date conditions
            app_end_keep = app_end_date is None or app_end_date.date() >= tomorrow
            auction_end_keep = (
                auction_end_date is None or auction_end_date.date() > future_14_days
            )

            # INN conditions
            inn_empty = not bankrupt_inn or bankrupt_inn.strip() == ""
            inn_valid = validate_inn(bankrupt_inn)
            inn_keep = not inn_empty or not REMOVE_EMPTY_INN
            inn_keep = inn_keep and (inn_valid or not REMOVE_INVALID_INN_LENGTH)

            # Overall keep condition: all filters must pass
            keep = app_end_keep and auction_end_keep and inn_keep

            if keep:
                filtered_items.append(item)
                reason = []
                if app_end_date is None:
                    reason.append("App empty")
                elif app_end_date.date() >= tomorrow:
                    reason.append(f"App {app_end_date_str}")

                if auction_end_date is None:
                    reason.append("Auction empty")
                elif auction_end_date.date() > future_14_days:
                    reason.append(f"Auction {auction_end_date_str}")

                if inn_empty:
                    reason.append("INN empty (allowed)")
                elif inn_valid:
                    reason.append(f"INN {bankrupt_inn} (valid)")
                else:
                    reason.append(f"INN {bankrupt_inn} (allowed)")

                keep_reasons.append(" | ".join(reason))
            else:
                removed_count += 1
                reasons = []

                if not app_end_keep:
                    reasons.append(f"App too soon: {app_end_date_str}")
                if not auction_end_keep:
                    reasons.append(f"Auction too soon: {auction_end_date_str}")
                if inn_empty and REMOVE_EMPTY_INN:
                    inn_empty_count += 1
                    reasons.append("Empty INN")
                if not inn_valid and REMOVE_INVALID_INN_LENGTH:
                    inn_invalid_count += 1
                    reasons.append(
                        f"Invalid INN: {bankrupt_inn} ({len(''.join(filter(str.isdigit, bankrupt_inn)))} digits)"
                    )

                remove_reasons.append("; ".join(reasons))

        # Update the data with filtered items
        data["items"] = filtered_items
        data["count"] = len(filtered_items)

        # Write filtered data to new file
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\nFiltering complete:")
        print(f"Original items: {original_count}")
        print(f"Removed: {removed_count}")
        print(
            f"  - Date filters: {original_count - removed_count - inn_empty_count - inn_invalid_count}"
        )
        print(f"  - Empty INN: {inn_empty_count}")
        print(f"  - Invalid INN length: {inn_invalid_count}")
        print(f"Remaining: {len(filtered_items)}")
        print(f"Output saved to: {output_file}")

        # Test with example
        print(f"\nExample test:")
        test_inn = "8602201830"  # 10 digits - valid
        test_empty_inn = ""
        test_invalid_inn = "12345678"  # 8 digits - invalid

        print(
            f"Valid INN '{test_inn}': {'KEEP' if validate_inn(test_inn) else 'REMOVE'}"
        )
        print(
            f"Empty INN '{test_empty_inn}': {'KEEP' if not REMOVE_EMPTY_INN else 'REMOVE'}"
        )
        print(
            f"Invalid INN '{test_invalid_inn}': {'KEEP' if not REMOVE_INVALID_INN_LENGTH else 'REMOVE'}"
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
