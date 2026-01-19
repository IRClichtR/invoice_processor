# Project context
This project aims to develop an advanced invoice processing system that leverages machine learning and natural language processing techniques to automate the extraction, validation, and organization of invoice data. The system will be designed to handle various invoice formats and layouts, ensuring high accuracy and efficiency in data processing.

# Objectives
1. Prioritize local processing of invoices to enhance data security and reduce dependency on external services.
2. Implement robust data extraction algorithms to accurately capture key invoice details.
3. Develop a user-friendly interface for easy interaction with the invoice processing system.
4. Application is deployed on a local server to ensure data privacy and control.

# Key Features
- Local Data Processing: Documents are processed by a local server. 
- For documents that cannot be processed locally, users are prompted to upload them to an external service (e.g., Claude) for processing.
- Data Extraction: Utilize machine learning models to extract relevant information
- Validation: Implement validation checks to ensure the accuracy of extracted data.
- User Interface: Design an intuitive interface for users to upload invoices and view processed data.

# Technologies Used
- Programming Languages: Python, Typescript, Vue.js for frontend, FastAPI for backend. Rust Tauri for desktop application.
- Database: SQLite for local data storage.
- Machine Learning Libraries: Tesseract OCR, Transformers, PyTorch, Pillow.
- Local models: Florence-2
- External API: Anthropic Claude API for fallback processing.

# AI assistant role
Prioritize code simplicity and readability. Ensure that the code is well-documented and follows best practices for maintainability. Focus on creating modular components that can be easily tested and integrated into the overall system.

# My TODO list
- [x] Set up local server environment for invoice processing.
- [x] Database schema design for storing invoice and other documents data.
- [x] Integrate Tesseract OCR for text extraction from invoice images.
- [x] PDF and image workflow for local processing.
- [x] Workflow for Claude API processing for documents that cannot be processed locally.
- [x] Develop frontend interface using Vue.js for user interaction.
- [x] Implement data validation checks for extracted invoice details.
- [ ] Finish claude workflow
- [ ] Finish Python API with get/post endpoints.
- [ ] Move fastAPI backend to sidecar in Tauri application.
- [ ] Tauri calls of API endpoints.
- [ ] Endpoints testing
- [ ] Frontend integration testing
- [ ] E2e
- [ ] GithHub Actions