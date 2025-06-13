from paddleocr import PaddleOCR
import cv2
import numpy as np
import re

# Initialize the OCR model
ocr = PaddleOCR(use_textline_orientation=False, lang='en')

def clean_text(text):
    """Clean and normalize text"""
    if not text:
        return ""
    # Remove extra spaces and normalize
    text = re.sub(r'\s+', ' ', text.strip())
    return text

def group_into_rows(boxes, texts, row_threshold=25):
    """
    Group text items into rows based on vertical position
    """
    if not boxes or not texts:
        return []
    
    # Create items with position info
    items = []
    for box, text in zip(boxes, texts):
        # Get bounding box coordinates
        y_coords = [pt[1] for pt in box]
        x_coords = [pt[0] for pt in box]
        
        y_center = sum(y_coords) / len(y_coords)
        x_left = min(x_coords)
        x_right = max(x_coords)
        
        items.append({
            'text': clean_text(text),
            'y_center': y_center,
            'x_left': x_left,
            'x_right': x_right,
            'box': box
        })
    
    # Sort by vertical position
    items.sort(key=lambda x: x['y_center'])
    
    # Group into rows
    rows = []
    current_row = []
    
    for item in items:
        if not current_row:
            current_row.append(item)
        else:
            # Check if this item belongs to the current row
            avg_y = sum(i['y_center'] for i in current_row) / len(current_row)
            if abs(item['y_center'] - avg_y) <= row_threshold:
                current_row.append(item)
            else:
                # Finish current row and start new one
                if current_row:
                    current_row.sort(key=lambda x: x['x_left'])
                    rows.append(current_row)
                current_row = [item]
    
    # Add the last row
    if current_row:
        current_row.sort(key=lambda x: x['x_left'])
        rows.append(current_row)
    
    return rows

def detect_table_regions(rows):
    """
    Detect which rows belong to tables vs regular text
    """
    table_regions = []
    text_regions = []
    
    i = 0
    while i < len(rows):
        row = rows[i]
        
        # Check if this looks like a table row
        if is_table_row(row, rows, i):
            # Start of a table region
            table_start = i
            
            # Find the end of the table
            while i < len(rows) and (is_table_row(rows[i], rows, i) or is_continuation_row(rows[i], rows, i)):
                i += 1
            
            table_end = i
            table_regions.append((table_start, table_end))
        else:
            # Regular text row
            text_regions.append(i)
            i += 1
    
    return table_regions, text_regions

def is_table_row(row, all_rows, row_index):
    """
    Determine if a row is part of a table
    """
    # Must have multiple columns
    if len(row) < 2:
        return False
    
    # Check if it contains mostly numeric data or key-value pairs
    numeric_count = 0
    for item in row:
        text = item['text']
        if re.search(r'\d', text) or text.lower() in ['month', 'january', 'february', 'march', 'april', 'may', 'june', 
                                                      'july', 'august', 'september', 'october', 'november', 'december',
                                                      'sales', 'rs', 'budget']:
            numeric_count += 1
    
    # If more than half the columns have numbers or table-related words
    return numeric_count >= len(row) * 0.4

def is_continuation_row(row, all_rows, row_index):
    """
    Check if this row continues a table (even if it has fewer columns)
    """
    if row_index == 0:
        return False
    
    # Look at previous rows to see if they were table rows
    prev_table_rows = 0
    for i in range(max(0, row_index - 3), row_index):
        if len(all_rows[i]) >= 2:
            prev_table_rows += 1
    
    # If we have recent table rows and this row has table-like content
    if prev_table_rows >= 1:
        text_content = ' '.join(item['text'] for item in row).lower()
        return bool(re.search(r'\d|rs|month|january|february|march|april|may|june|july|august|september|october|november|december', text_content))
    
    return False

def format_table(table_rows):
    """
    Format rows as a clean table
    """
    if not table_rows:
        return ""
    
    # Determine maximum columns needed
    max_cols = max(len(row) for row in table_rows)
    
    # Create table data
    table_data = []
    for row in table_rows:
        row_data = [item['text'] for item in row]
        # Pad with empty strings if needed
        while len(row_data) < max_cols:
            row_data.append("")
        table_data.append(row_data)
    
    if not table_data:
        return ""
    
    # Calculate column widths
    col_widths = [0] * max_cols
    for row in table_data:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Ensure minimum width
    col_widths = [max(w, 8) for w in col_widths]
    
    # Format table
    lines = []
    
    # Header separator
    separator = "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"
    
    for i, row in enumerate(table_data):
        # Format row
        formatted_cells = []
        for j, cell in enumerate(row):
            formatted_cells.append(f" {str(cell).ljust(col_widths[j])} ")
        
        line = "|" + "|".join(formatted_cells) + "|"
        lines.append(line)
        
        # Add separator after first row (if it looks like a header)
        if i == 0 and len(table_data) > 1:
            lines.append(separator)
    
    return "\n".join(lines)

def format_text_paragraph(text_rows):
    """
    Format regular text rows as paragraphs
    """
    paragraphs = []
    current_paragraph = []
    
    for row in text_rows:
        text = " ".join(item['text'] for item in row)
        
        # Check if this starts a new paragraph
        if (text.strip().endswith(':') or 
            text.strip().startswith(('a.', 'b.', 'c.', 'd.')) or
            len(current_paragraph) > 0 and len(text) < 50):
            
            if current_paragraph:
                paragraphs.append(" ".join(current_paragraph))
                current_paragraph = []
        
        current_paragraph.append(text)
    
    if current_paragraph:
        paragraphs.append(" ".join(current_paragraph))
    
    return paragraphs

def process_image(image_path):
    """
    Main function to process image and extract organized text
    """
    # Read the image
    img = cv2.imread(image_path)
    if img is None:
        print("Failed to read the image.")
        return
    
    # Run OCR using predict method
    result = ocr.predict(img)
    
    # Handle the PaddleOCR result format
    if not result or len(result) == 0:
        print("No text detected")
        return
    
    # Extract from the complex result structure
    ocr_result = result[0] if isinstance(result, list) else result
    
    # Get text and boxes from the result dictionary
    if isinstance(ocr_result, dict):
        if 'rec_texts' in ocr_result and 'rec_boxes' in ocr_result:
            texts = ocr_result['rec_texts']
            boxes = ocr_result['rec_boxes']
            confidences = ocr_result.get('rec_scores', [1.0] * len(texts))
            
            # Filter by confidence and clean up
            filtered_boxes = []
            filtered_texts = []
            
            for text, box, conf in zip(texts, boxes, confidences):
                if conf > 0.6 and text.strip():  # Higher confidence threshold
                    # Convert box format to list of points
                    box_points = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]
                    filtered_boxes.append(box_points)
                    filtered_texts.append(text)
            
            if not filtered_texts:
                print("No text detected")
                return
            
        else:
            print("No text detected")
            return
    else:
        print("No text detected")
        return
    
    # Group text into rows
    rows = group_into_rows(filtered_boxes, filtered_texts)
    
    if not rows:
        print("No text detected")
        return
    
    # Detect table regions
    table_regions, text_regions = detect_table_regions(rows)
    
    print("ORGANIZED TEXT OUTPUT")
    print("=" * 60)
    
    # Process and display results
    processed_regions = []
    
    # Mark all regions with their types
    for start, end in table_regions:
        for i in range(start, end):
            processed_regions.append((i, 'table'))
    
    for i in text_regions:
        processed_regions.append((i, 'text'))
    
    # Sort by row index
    processed_regions.sort()
    
    # Group consecutive regions of same type
    current_group = []
    current_type = None
    
    for row_idx, region_type in processed_regions:
        if region_type != current_type:
            # Process previous group
            if current_group and current_type:
                if current_type == 'table':
                    table_rows = [rows[i] for i in current_group]
                    print(f"\n📊 TABLE:")
                    print("-" * 40)
                    print(format_table(table_rows))
                else:
                    text_rows = [rows[i] for i in current_group]
                    paragraphs = format_text_paragraph(text_rows)
                    print(f"\n📄 TEXT:")
                    print("-" * 40)
                    for para in paragraphs:
                        print(f"{para}\n")
            
            current_group = [row_idx]
            current_type = region_type
        else:
            current_group.append(row_idx)
    
    # Process last group
    if current_group and current_type:
        if current_type == 'table':
            table_rows = [rows[i] for i in current_group]
            print(f"\n📊 TABLE:")
            print("-" * 40)
            print(format_table(table_rows))
        else:
            text_rows = [rows[i] for i in current_group]
            paragraphs = format_text_paragraph(text_rows)
            print(f"\n📄 TEXT:")
            print("-" * 40)
            for para in paragraphs:
                print(f"{para}\n")
    
    print("\n" + "=" * 60)

# Example usage
if __name__ == "__main__":
    process_image("data/test.jpeg")