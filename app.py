from flask import Flask, render_template, request, send_file, redirect, url_for, flash
import os
import pandas as pd
from playwright.sync_api import sync_playwright
from textblob import TextBlob
from PIL import Image, ImageEnhance, ImageOps
import pytesseract
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)

# Set directories for storing screenshots and comments
instagram_screenshot_dir = "static/images"
tweet_screenshot_dir = os.path.join("static", "tweet_screenshots")
tweet_text_dir = os.path.join("static", "tweet_texts")

os.makedirs(instagram_screenshot_dir, exist_ok=True)
os.makedirs(tweet_screenshot_dir, exist_ok=True)
os.makedirs(tweet_text_dir, exist_ok=True)

# Remove the secret key initialization
# app.secret_key = secrets.token_hex(16)  # Commenting this line

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_instagram', methods=['POST'])
def process_instagram():
    instagram_url = request.form.get('instagram_url')

    if not instagram_url:
        flash("Please provide an Instagram post URL.")
        return redirect(url_for('index'))

    try:
        extracted_text, sentiment, screenshot_path = take_screenshot_and_extract_text(instagram_url)
        filename = screenshot_path.split('/')[-1]
        return render_template('result.html', image_path=filename, text=extracted_text, sentiment=sentiment)
    except Exception as e:
        flash(f"Error processing the Instagram post: {e}")
        return redirect(url_for('index'))

@app.route('/process_tweet', methods=['POST'])
def process_tweet():
    profile_url = request.form.get('profile_url')

    if not profile_url:
        flash("Please provide an X.com profile URL.")
        return redirect(url_for('index'))

    try:
        profile_data = scrape_profile(profile_url)
        tweet_id = profile_data.get("id", "unknown")
        return render_template('result.html', 
                               image_path=profile_data['screenshot'],
                               text_path=profile_data['text_file'],
                               text=profile_data['text'])
    except Exception as e:
        flash(f"Error processing the X.com profile: {e}")
        return redirect(url_for('index'))

def take_screenshot_and_extract_text(url: str):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        page.goto(url)

        try:
            page.wait_for_selector("article", timeout=10000)
            post_id = url.split('/')[-2]
            page.wait_for_timeout(5000)
            screenshot_path = os.path.join(instagram_screenshot_dir, f"post_{post_id}.png")
            page.screenshot(path=screenshot_path)
            extracted_text = extract_text_from_image(screenshot_path)

            if extracted_text:
                sentiment = analyze_text(extracted_text)
                return extracted_text, sentiment, screenshot_path
            else:
                raise Exception("No text found in the screenshot!")

        except Exception as e:
            raise e
        finally:
            browser.close()

def scrape_profile(url: str) -> dict:
    _xhr_calls = []

    def intercept_response(response):
        if response.request.resource_type == "xhr":
            _xhr_calls.append(response)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.on("response", intercept_response)
        page.goto(url)
        page.wait_for_selector("[data-testid='primaryColumn']")
        page.wait_for_timeout(3000)

        tweet_element = page.query_selector(f'[data-testid="tweet"]')
        tweet_id = url.split('/')[-1]

        if tweet_element:
            tweet_text = tweet_element.text_content()
            screenshot_path = os.path.join(tweet_screenshot_dir, f"tweet_{tweet_id}.png")
            tweet_element.screenshot(path=screenshot_path)
            text_file_path = os.path.join(tweet_text_dir, f"tweet_{tweet_id}.txt")
            with open(text_file_path, "w", encoding="utf-8") as text_file:
                text_file.write(tweet_text.strip())
            return {
                "id": tweet_id,
                "text": tweet_text.strip(),
                "screenshot": screenshot_path,
                "text_file": text_file_path
            }
        else:
            screenshot_path = os.path.join(tweet_screenshot_dir, f"page_{tweet_id}.png")
            page.screenshot(path=screenshot_path)
            page_text = page.text_content().strip()
            text_file_path = os.path.join(tweet_text_dir, f"page_{tweet_id}.txt")
            with open(text_file_path, "w", encoding="utf-8") as text_file:
                text_file.write(page_text)
            return {
                "id": tweet_id,
                "text": page_text,
                "screenshot": screenshot_path,
                "text_file": text_file_path
            }

def extract_text_from_image(image_path: str) -> str:
    img = Image.open(image_path)
    img = ImageOps.grayscale(img)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2)
    custom_config = r'--oem 3 --psm 6'
    text = pytesseract.image_to_string(img, config=custom_config)
    return text.strip()

def analyze_text(text: str) -> float:
    blob = TextBlob(text)
    return blob.sentiment.polarity

@app.route('/download_image/<filename>')
def download_image(filename):
    file_path = os.path.join(instagram_screenshot_dir, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        file_path = os.path.join(tweet_screenshot_dir, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            flash(f"File {filename} not found. Please make sure the file exists.")
            return redirect(url_for('index'))

@app.route('/download_text/<filename>')
def download_text(filename):
    file_path = os.path.join(tweet_text_dir, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        flash(f"File {filename} not found. Please make sure the file exists.")
        return redirect(url_for('index'))

@app.route('/download_excel')
def download_excel():
    text = request.args.get('text')
    if not text:
        flash("No text available for generating Excel.")
        return redirect(url_for('index'))

    excel_path = os.path.join(instagram_screenshot_dir, 'extracted_data.xlsx')
    df = pd.DataFrame({'Extracted Text': [text]})
    df.to_excel(excel_path, index=False)
    return send_file(excel_path, as_attachment=True)

@app.route('/download_pdf')
def download_pdf():
    text = request.args.get('text')
    if not text:
        flash("No text available for generating PDF.")
        return redirect(url_for('index'))

    try:
        if not os.path.exists(instagram_screenshot_dir):
            os.makedirs(instagram_screenshot_dir)

        pdf_path = os.path.join(instagram_screenshot_dir, 'extracted_data_reportlab.pdf')

        c = canvas.Canvas(pdf_path, pagesize=letter)
        c.setFont("Helvetica", 12)
        text_object = c.beginText(40, 750)
        text_object.setFont("Helvetica", 12)
        text_object.textLines(text)
        c.drawText(text_object)
        c.showPage()
        c.save()

        return send_file(pdf_path, as_attachment=True)

    except Exception as e:
        flash(f"Error generating PDF: {e}")
        return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug=True)
