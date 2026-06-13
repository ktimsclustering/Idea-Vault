import urllib.request
import json

IDEAS = [
    "A smart plant pot that waters itself based on soil moisture and ambient humidity sensors.",
    "A local-first AI coding assistant that indexes your entire codebase and works offline.",
    "A meal planning app that creates recipes strictly from ingredients you already have in your fridge.",
    "A gamified fitness tracker where you level up an RPG character based on real-life workouts.",
    "An interactive map for street art and murals, crowdsourced by the community with artist credits."
]

def add_idea(text):
    req = urllib.request.Request(
        "http://127.0.0.1:5000/api/ideas",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"✅ Created idea: {data.get('title')}")
    except Exception as e:
        print(f"❌ Failed to create idea: {e}")

if __name__ == "__main__":
    print("Generating test ideas...")
    for idea in IDEAS:
        add_idea(idea)
    print("Done!")
