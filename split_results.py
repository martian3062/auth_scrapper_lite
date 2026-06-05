import os
import json

def split_results(input_file="ctri_results.json", output_dir="results"):
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return

    os.makedirs(output_dir, exist_ok=True)
    print(f"Reading {input_file}...")
    
    with open(input_file, "r", encoding="utf-8") as f:
        trials = json.load(f)
        
    print(f"Loaded {len(trials)} trials. Splitting into individual files in '{output_dir}'...")
    
    count = 0
    for trial in trials:
        ctri_number = trial.get("ctri_number")
        if not ctri_number:
            continue
            
        # Clean CTRI number for filename compatibility (replace '/' with '_')
        safe_filename = ctri_number.replace("/", "_") + ".json"
        filepath = os.path.join(output_dir, safe_filename)
        
        with open(filepath, "w", encoding="utf-8") as out_f:
            json.dump(trial, out_f, indent=2, ensure_ascii=False)
        count += 1
        
    print(f"Successfully wrote {count} individual files to '{output_dir}'.")

if __name__ == "__main__":
    split_results()
