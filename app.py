from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os
from scraper_module import run_scraper

app = FastAPI()

# Store status of scraping tasks
tasks = {}

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r") as f:
        return f.read()

@app.post("/scrape/{location}")
async def start_scrape(location: str, background_tasks: BackgroundTasks, max_pages: int = 3):
    tasks[location] = "Running"
    background_tasks.add_task(handle_scrape, location, max_pages)
    return {"message": "Scraping started", "location": location}

def handle_scrape(location: str, max_pages: int):
    try:
        from scraper_module import run_scraper
        csv_file = run_scraper(location, max_pages=max_pages)
        if csv_file:
            tasks[location] = {"status": "Completed", "file": csv_file}
        else:
            tasks[location] = {"status": "Failed", "error": "No data found"}
    except Exception as e:
        tasks[location] = {"status": "Failed", "error": str(e)}

@app.get("/status/{location}")
async def get_status(location: str):
    return tasks.get(location, {"status": "Not Started"})

@app.get("/download/{location}")
async def download_file(location: str):
    task = tasks.get(location)
    if task and isinstance(task, dict) and task.get("status") == "Completed":
        return FileResponse(task["file"], filename=task["file"], media_type='text/csv')
    return {"error": "File not ready"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
