### This script processes a CSV file containing scientific articles, uploads the associated PDF files to OpenAI's API,
### and uses the API to analyze the papers. The results are saved in a new CSV file.
### 
### Initial set-up:
### 1. Set up a virtual environment and activate it.
###     - python3 -m venv venv
###     - source venv/bin/activate  # On Windows use `venv\Scripts\activate`
### 2. Install the required libraries:
###     - pip install openai pandas
### 3. Set up your OpenAI API key in the script.
### 4. Ensure the CSV file with articles is in the correct format and located in "./data/articles-full-screen.csv". To generate the CSV file:
###     - Open Zotero and select the collection you want to export.
###     - Click on the "File" menu and select "Export Library".
###     - Choose the format "CSV" and select the location and filename to "./data/articles-full-screen.csv" to save the file.
###     - Click "OK" to export the library.
### 5. Run the script to process the articles and save the results in a new CSV file.

# import necessary libraries
import pandas as pd
import os
import time
import json
from openai import OpenAI

# Initialize OpenAI client with your API key
client = OpenAI(api_key="ADD-YOUR-API-KEY-HERE")

# Load the CSV file containing the articles
articles_df = pd.read_csv('./data/articles-full-screen.csv', delimiter=',')
print(articles_df.columns)
print(articles_df.head())

# Sort the articles by Author and reset index
articles_df = articles_df.sort_values(by='Author').reset_index(drop=True)

# Define output CSV filename and ordered columns (ensure they match the JSON keys exactly)
output_csv = "./results/articles-full-screen-results.csv"
columns_order = [
    "DOI", "Title", "Author", "Publication Year",
    "Type", "Keywords", 
    "Specific Dis ease(s)", "Specific Modeling Approach(es)", "Specific Social Contexts",
    "Specific Populations", "Specific Geographical Location", "Specific Time Periods",
    "Specific Data Sources", "Other Factors",
    "Score (Public Health Relevance)", "Comment (Public Health Relevance)",
    "Score (Modeling Relevance)", "Comment (Modeling Relevance)",
    "Challenges", "Recommendations",
    "Score (Evidence Base)", "Comment (Evidence Base)",
    "Score (Breadth of Discussion)", "Comment (Breadth of Discussion)",
    "Score (Acknowledgment of Uncertainty & Bias)", "Comment (Acknowledgment of Uncertainty & Bias)",
    "Score (Transparency)", "Comment (Transparency)"
]

# Create the output directory if it doesn't exist
output_dir = "./results"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# A dictionary to cache uploaded files so each PDF is uploaded only once.
uploaded_files = {}

# Function to append a list of result dictionaries (one per paper) to the CSV.
def append_to_csv(results_list):
    df_chunk = pd.DataFrame(results_list, columns=columns_order)
    if os.path.exists(output_csv):
        df_chunk.to_csv(output_csv, mode='a', index=False, header=False)
    else:
        df_chunk.to_csv(output_csv, mode='w', index=False, header=True)
    print(f"Appended {len(results_list)} rows to {output_csv}")

# Function to clean GPT's response text by removing markdown code fences.
def clean_json_response(response_str):
    # Remove leading/trailing backticks and "json"
    response_str = response_str.strip()
    if response_str.startswith("```json"):
        response_str = response_str.split("```json", 1)[1]
    if response_str.endswith("```"):
        response_str = response_str.rsplit("```", 1)[0]
    return response_str.strip()

# Set the chunk size to update the CSV every 5 papers.
chunk_size = 5
chunk_results = []
processed_count = 0

# Loop over each article in the input CSV.
for index, row in articles_df.iterrows():
    author = row['Author']
    year = row['Publication Year']
    title = row['Title']
    journal = row['Publication Title']
    volume = row['Volume']
    issue = row['Issue']
    pages = row['Num Pages']
    DOI = row['DOI']
    file_path = row['File Attachments']

    # Skip if no file available.
    if pd.isnull(file_path):
        print(f"Skipping paper with missing file: {title}")
        continue

    # Use cached file id if already uploaded.
    if file_path in uploaded_files:
        file_id = uploaded_files[file_path]
    else:
        try:
            with open(file_path, "rb") as file:
                file_upload_response = client.files.create(
                    file=file,
                    purpose='assistants'
                )
                file_id = file_upload_response.id
                uploaded_files[file_path] = file_id
                print(f"File uploaded successfully for {title}.")
        except Exception as e:
            print(f"Error uploading file for {title}: {e}")
            continue

    # Build the prompt for ChatGPT.
    # Note: The prompt instructs the assistant to return the result as valid JSON with keys that
    # exactly match the output CSV columns (except the initial 4 columns which come from the input).
    prompt = f"""
Task: You are a scientific paper reviewer. You are provided with a PDF file of a scientific paper (attached) and must respond in valid JSON format with exactly the following keys:
- Type
- Keywords
- Specific Disease(s)
- Specific Modeling Approach(es)
- Specific Social Contexts
- Specific Populations
- Specific Geographical Location
- Specific Time Periods
- Specific Data Sources
- Other Factors
- Score (Public Health Relevance)
- Comment (Public Health Relevance)
- Score (Modeling Relevance)
- Comment (Modeling Relevance)
- Challenges
- Recommendations
- Score (Evidence Base)
- Comment (Evidence Base)
- Score (Breadth of Discussion)
- Comment (Breadth of Discussion)
- Score (Acknowledgment of Uncertainty & Bias)
- Comment (Acknowledgment of Uncertainty & Bias)
- Score (Transparency)
- Comment (Transparency)

For each key, follow these instructions precisely:
1. **Type**: classify the paper into one of the following categories: Opinion piece, Editorial, Reflection, Perspective article, Commentary, Letter, Review article, Meta-analysis, Research article, Conference paper, Technical report, Thesis, Book chapter, Book, Policy paper, Other (please specify). If the paper type is mentioned in the title or abstract, use this. Generate only the paper type, no explanation.
2. **Keywords**: List typical keywords (maximum 10 keywords) separated by commas, no extra text.
3. **Specific Disease(s)**: List the diseases the paper's discussion specifically and exclusively applies to. If they are only briefly mentioned or not explicitly stated, output "NA".
4. **Specific Modeling Approach(es)**: List the modeling approaches the paper's discussion specifically and exclusively applies to. If they are only briefly mentioned or not explicitly stated, output "NA".
5. **Specific Social Contexts**: List the social contexts the paper's discussion specifically and exclusively applies to. If they are only briefly mentioned or not explicitly stated, output "NA".
6. **Specific Populations**: List the populations the paper's discussion specifically and exclusively applies to. If they are only briefly mentioned or not explicitly stated, output "NA".
7. **Specific Geographical Location**: List the geographical locations the paper's discussion specifically and exclusively applies to. If they are only briefly mentioned or not explicitly stated, output "NA".
8. **Specific Time Periods**: List the time periods the paper's discussion specifically and exclusively applies to. If they are only briefly mentioned or not explicitly stated, output "NA".
9. **Specific Data Sources**: List the data sources the paper's discussion specifically and exclusively applies to. If they are only briefly mentioned or not explicitly stated, output "NA".
10. **Other Factors**: List any other factor the paper's discussion specifically and exclusively applies to. If a factor is only briefly mentioned or not explicitly stated, output "NA".

11. **Score (Public Health Relevance)**: Is the paper aligned with the following inclusion/exclusion criteria: "The paper must discuss how mathematical models contribute to public health decision-making, including but not limited to policymaking, pandemic/epidemic preparedness, interventions, and resource allocation. Papers that exclusively focus on theoretical model development without discussing real-world applications or policy implications are excluded." Give a score: 0 (does not meet the criteria), 1 (partially meets the criteria), or 2 (fully meets the criteria). Give only one number (which score applies), nothing else.
12. **Comment (Public Health Relevance)**: Is the paper aligned with the following inclusion/exclusion criteria: "The paper must discuss how mathematical models contribute to public health decision-making, including but not limited to policymaking, pandemic/epidemic preparedness, interventions, and resource allocation. Papers that exclusively focus on theoretical model development without discussing real-world applications or policy implications are excluded." Give a keyword summary of why the paper does or does not meet the criteria. Do not generate full sentences but a brief and comprehensible summary.
13. **Score (Modeling Relevance)**: Is the paper aligned with the following inclusion/exclusion criteria: Is the paper aligned with the following inclusion/exclusion criteria: “The paper must include a critical discussion of the role, challenges, limitations, gaps, or future research directions in infectious disease modeling. Papers that exclusively present a model and its results without discussing its implications, strengths, or weaknesses are excluded. The paper must go substantially beyond presenting a single model and its implications by taking a broader perspective on mathematical modeling, including but not limited to opinion pieces, perspective articles, editorials, reviews, and general discussions. Papers that exclusively present and discuss a single model, its results, or technical modeling aspects (e.g., parameter estimation, numerical solutions, computational efficiency, scenario-specific results) without discussing broader insights, challenges, or future directions in infectious disease modeling are excluded.” Give a score: 0 (does not meet the criteria), 1 (partially meets the criteria), or 2 (fully meets the criteria). Give only one number (which score applies), nothing else.
14. **Comment (Modeling Relevance)**: Is the paper aligned with the following inclusion/exclusion criteria: Is the paper aligned with the following inclusion/exclusion criteria: “The paper must include a critical discussion of the role, challenges, limitations, gaps, or future research directions in infectious disease modeling. Papers that exclusively present a model and its results without discussing its implications, strengths, or weaknesses are excluded. The paper must go substantially beyond presenting a single model and its implications by taking a broader perspective on mathematical modeling, including but not limited to opinion pieces, perspective articles, editorials, reviews, and general discussions. Papers that exclusively present and discuss a single model, its results, or technical modeling aspects (e.g., parameter estimation, numerical solutions, computational efficiency, scenario-specific results) without discussing broader insights, challenges, or future directions in infectious disease modeling are excluded.” Give a keyword summary of why the paper does or does not meet the criteria. Do not generate full sentences but a brief and comprehensible summary.
15. **Challenges**: Summarize all challenges and issues regarding mathematical modeling of infectious disease for public health explicitly discussed in the paper. Use bullet points, starting with a "-" to summarize the challenges and recommendations. Summarize each challenge/issue as briefly as possible.
16. **Recommendations**: Summarize all recommendations and future research options regarding mathematical modeling of infectious disease for public health explicitly discussed in the paper. Use bullet points, starting with a "-" to summarize the challenges and recommendations. Summarize each challenge/issue as briefly as possible.
17. **Score (Evidence Base)**: Does the paper provide references to support its claims, or is it based purely on opinion? Does it cite key sources, reviews, or seminal works in the field? Give a score: 0 (does not meet the criteria), 1 (partially meets the criteria), or 2 (fully meets the criteria). Give only one number (which score applies), nothing else.
18. **Comment (Evidence Base)**: Does the paper provide references to support its claims, or is it based purely on opinion? Does it cite key sources, reviews, or seminal works in the field? Give a keyword summary of why the paper does or does not meet the criteria. Do not generate full sentences but a brief and comprehensible summary.
19. **Score (Breadth of Discussion)**: Does the paper discuss multiple aspects of modeling challenges and does it take a holistic perspective (high score), or is the discussion limited to a narrow topic or limited aspects of modeling (low score)? Give a score: 0 (does not meet the criteria), 1 (partially meets the criteria), or 2 (fully meets the criteria). Give only one number (which score applies), nothing else.
20. **Comment (Breadth of Discussion)**: Does the paper discuss multiple aspects of modeling challenges and does it take a holistic perspective, or is the discussion limited to a narrow topic or limited aspects of modeling? Give a keyword summary of why the paper does or does not meet the criteria. Do not generate full sentences but a brief and comprehensible summary.
21. **Score (Acknowledgment of Uncertainty & Bias)**: Does the paper discuss limitations, biases, or uncertainties in infectious disease modeling and does it provide a balanced view (high score), or does it strongly advocate for a single perspective (low score)? Give a score: 0 (does not meet the criteria), 1 (partially meets the criteria), or 2 (fully meets the criteria). Give only one number (which score applies), nothing else.
22. **Comment (Acknowledgment of Uncertainty & Bias)**: Does the paper discuss limitations, biases, or uncertainties in infectious disease modeling and does it provide a balanced view, or does it strongly advocate for a single perspective? Give a keyword summary of why the paper does or does not meet the criteria. Do not generate full sentences but a brief and comprehensible summary.
23. **Score (Transparency)**: Are the authors transparent in how they came to their conclusions? For example: If it is a review paper, does it describe how studies were selected and synthesized? If it is an opinion piece, editorial, comment, etc., do the authors disclose their background or potential conflicts of interest? If it is a research article, are the methods explained in a way that enables replication? Give a score: 0 (does not meet the criteria), 1 (partially meets the criteria), or 2 (fully meets the criteria). Give only one number (which score applies), nothing else.
24. **Comment (Transparency)**: Are the authors transparent in how they came to their conclusions? For example: If it is a review paper, does it describe how studies were selected and synthesized? If it is an opinion piece, editorial, comment, etc., do the authors disclose their background or potential conflicts of interest? If it is a research article, are the methods explained in a way that enables replication? Give a keyword summary of why the paper does or does not meet the criteria. Do not generate full sentences but a brief and comprehensible summary.

Return only the JSON object and nothing else.
"""

    try:
        # Create an Assistant
        assistant = client.beta.assistants.create(
            name="Scientific Paper Reviewer",
            instructions="You are an expert in scientific paper review.",
            model="gpt-4o-mini",
            tools=[{"type": "file_search"}]
        )

        # Create a Thread
        thread = client.beta.threads.create()

        # Send a message with the prompt and attached file.
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=prompt,
            attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]}]
        )

        # Run the Assistant
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id
        )

        # Poll until the run is completed.
        while True:
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            if run_status.status == "completed":
                break
            elif run_status.status in ["failed", "cancelled", "expired"]:
                raise Exception(f"Run failed with status: {run_status.status}, error: {getattr(run_status, 'last_error', 'No error details')}")
            time.sleep(2)

        # Retrieve the assistant's response from the thread.
        messages_list = client.beta.threads.messages.list(thread_id=thread.id)
        assistant_messages = [msg for msg in messages_list.data if msg.role == "assistant"]
        if assistant_messages:
            gpt_response_text = ""
            for content_item in assistant_messages[0].content:
                if content_item.type == "text":
                    gpt_response_text += content_item.text.value
        else:
            gpt_response_text = "{}"  # Default to empty JSON if no response.

        # Clean the response to remove markdown code fences.
        gpt_response_text = clean_json_response(gpt_response_text)
        
        # Clean up the Assistant
        client.beta.assistants.delete(assistant_id=assistant.id)

        # Attempt to parse the JSON response.
        try:
            parsed_output = json.loads(gpt_response_text)
        except Exception as json_e:
            parsed_output = {}
            print(f"Error parsing JSON for paper '{title}': {json_e}. Response: {gpt_response_text}")

        # Build the row using the original paper info plus parsed results.
        row_result = {
            "Author": author,
            "Year": year,
            "Title": title,
            "Journal/Publisher": journal,
            "Volume": volume,
            "Issue": issue,
            "Pages": pages,
            "DOI": DOI,
            "Type": parsed_output.get("Type", ""),
            "Keywords": parsed_output.get("Keywords", ""),
            "Specific Disease(s)": parsed_output.get("Specific Disease(s)", ""),
            "Specific Modeling Approach(es)": parsed_output.get("Specific Modeling Approach(es)", ""),
            "Specific Social Contexts": parsed_output.get("Specific Social Contexts", ""),
            "Specific Populations": parsed_output.get("Specific Populations", ""),
            "Specific Geographical Location": parsed_output.get("Specific Geographical Location", ""),
            "Specific Time Periods": parsed_output.get("Specific Time Periods", ""),
            "Specific Data Sources": parsed_output.get("Specific Data Sources", ""),
            "Other Factors": parsed_output.get("Other Factors", ""),
            "Score (Public Health Relevance)": parsed_output.get("Score (Public Health Relevance)", ""),
            "Comment (Public Health Relevance)": parsed_output.get("Comment (Public Health Relevance)", ""),
            "Score (Modeling Relevance)": parsed_output.get("Score (Modeling Relevance)", ""),
            "Comment (Modeling Relevance)": parsed_output.get("Comment (Modeling Relevance)", ""),
            "Challenges": parsed_output.get("Challenges", ""),
            "Recommendations": parsed_output.get("Recommendations", ""),
            "Score (Evidence Base)": parsed_output.get("Score (Evidence Base)", ""),
            "Comment (Evidence Base)": parsed_output.get("Comment (Evidence Base)", ""),
            "Score (Breadth of Discussion)": parsed_output.get("Score (Breadth of Discussion)", ""),
            "Comment (Breadth of Discussion)": parsed_output.get("Comment (Breadth of Discussion)", ""),
            "Score (Acknowledgment of Uncertainty & Bias)": parsed_output.get("Score (Acknowledgment of Uncertainty & Bias)", ""),
            "Comment (Acknowledgment of Uncertainty & Bias)": parsed_output.get("Comment (Acknowledgment of Uncertainty & Bias)", ""),
            "Score (Transparency)": parsed_output.get("Score (Transparency)", ""),
            "Comment (Transparency)": parsed_output.get("Comment (Transparency)", "")
        }

        processed_count += 1
        chunk_results.append(row_result)
        print(f"Processed paper {processed_count}: {title}")

        # Every 5 papers, append the current chunk to CSV and reset the chunk.
        if processed_count % chunk_size == 0:
            append_to_csv(chunk_results)
            chunk_results = []

    except Exception as e:
        print(f"Error in API call for paper '{title}': {e}")
        processed_count += 1
        row_result = {
            "Author": author,
            "Year": year,
            "Title": title,
            "Journal/Publisher": journal,
            "Volume": volume,
            "Issue": issue,
            "Pages": pages,
            "DOI": DOI,
            "Type": "",
            "Keywords": "",
            "Specific Disease(s)": "",
            "Specific Modeling Approach(es)": "",
            "Specific Social Contexts": "",
            "Specific Populations": "",
            "Specific Geographical Location": "",
            "Specific Time Periods": "",
            "Specific Data Sources": "",
            "Other Factors": "",
            "Score (Public Health Relevance)": "",
            "Comment (Public Health Relevance)": f"Error: {e}",
            "Score (Modeling Relevance)": "",
            "Comment (Modeling Relevance)": "",
            "Challenges": "",
            "Recommendations": "",
            "Score (Evidence Base)": "",
            "Comment (Evidence Base)": "",
            "Score (Breadth of Discussion)": "",
            "Comment (Breadth of Discussion)": "",
            "Score (Acknowledgment of Uncertainty & Bias)": "",
            "Comment (Acknowledgment of Uncertainty & Bias)": "",
            "Score (Transparency)": "",
            "Comment (Transparency)": ""
        }
        chunk_results.append(row_result)
        if processed_count % chunk_size == 0:
            append_to_csv(chunk_results)
            chunk_results = []

# After all papers are processed, if any remain, write them to CSV.
if chunk_results:
    append_to_csv(chunk_results)
    chunk_results = []

print(f"Processing complete. Total papers processed: {processed_count}")