import os

env_path = ".env"
new_lines = []
found_redirect = False

if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "8550" in line:
                print(f"Removing line with 8550: {line.strip()}")
                continue
            if line.strip().startswith("REDIRECT_URI"):
                print(f"Updating REDIRECT_URI: {line.strip()}")
                new_lines.append("REDIRECT_URI=http://localhost:8000/auth/callback\n")
                found_redirect = True
            else:
                new_lines.append(line)

    if not found_redirect:
        print("Adding REDIRECT_URI to .env")
        new_lines.append("\nREDIRECT_URI=http://localhost:8000/auth/callback\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("Finished cleaning .env")
else:
    print(".env file not found")
