### Annotaion Service

backend API.

_Supported OS:_ **Linux & Mac**

## Prerequisites

- Docker
- Neo4j or Neo4j Aura account
- Mongodb database

**Follow these steps to run :**

1. **Clone the Repository**:

   ```sh
   git clone https://github.com/rejuve-bio/annotation-query-backend.git
   cd annotation-query-backend
   ```

2. **Set Up the Virtual Environment**:

   ```sh
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**:

   ```sh
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Create a `.env` file in the root folder with the following content:
   ```plaintext
   NEO4J_URL=your_neo4j_url
   NEO4J_USERNAME =your_neo4j_user
   NEO4J_PASSWORD=your_neo4j_password
   ```
5. **Flask-Mail Configuration**:
   Add the following environment variables for email functionality:
   `MAIL_SERVER`: The address of the mail server that the application will use to send emails (e.g., smtp.gmail.com for Gmail).

   `MAIL_PORT`: The port number used by the mail server. Common ports include 587 for TLS (Transport Layer Security) or 465 for SSL (Secure Sockets Layer).

   `MAIL_USE_TLS`: If set to True, this enables Transport Layer Security (TLS) for securing the email transmission. Typically used with port 587.

   `MAIL_USE_SSL`: If set to True, this enables SSL (Secure Sockets Layer) for securing the email transmission. Typically used with port 465. It is not used when MAIL_USE_TLS is enabled

   `MAIL_USERNAME`: The email account username that will be used to authenticate with the mail serve

   `MAIL_PASSWORD`: The password or app-specific password (for services like Gmail) for the mail account used for sending emails.

   `MAIL_DEFAULT_SENDER`: The default email address that will appear in the "From" field of outgoing emails if the sender is not specified in the email message.

   ```plaintext
    MAIL_SERVER=smtp.example.com
    MAIL_USERNAME=your_email_username
    MAIL_PASSWORD=your_email_password
    MAIL_DEFAULT_SENDER=your_default_sender@example.com
    MAIL_USE_TLS=True/False
    MAIL_USE_SSL=True/False
    MAIL_PORT=port number
   ```

6. **Setup Required Folders**:
   Ensure the following folders are present in the root directory and contain the necessary data:

   metta_data: Folder for storing Metta data.
   cypher_data: Folder for storing Neo4j data.


7. **Choose Your Database Type**
   In the config directory modify config.yaml to change between databses.

   - To use Metta, set the type to 'metta'.
   - To use Neo4j, set the type to 'cypher'.

   Example

   ```config
   database
    type = cypher  # Change to 'metta' if needed
   ```
8. **Set Up MongoDB Database and LLM Keys**:

   Configure the `.env` file with the following settings:

   - Set the `MONGO_URI` to your MongoDB database URL, where the history will be stored:

     ```plaintext
     MONGO_URI=your_mongodb_url
     ```

   - For title generation and graph summarization, set the `LLM_MODEL` in the `.env` file to specify the large language model:

     - If `LLM_MODEL` is set to `openai`, the application will use the `OPENAI_API_KEY` from the `.env` file.
     - If `LLM_MODEL` is set to `gemini`, the application will use the `GEMINI_API_KEY` from the `.env` file.

9. **Run the Application**:

```sh
flask run
```

# Alternatively, you can use Docker to run the application:

**Build and Run the Docker Container**

1. **Setup Required Folders**:
   Ensure the following folders are present in the root directory and contain the necessary data:

   metta_data: Folder for storing Metta data.
   cypher_data: Folder for storing Neo4j data.

2. **Configure Environment Variables**:
   Create a `.env` file in the root folder with the following content:
   ```plaintext
   NEO4J_URL=your_neo4j_url
   NEO4J_USERNAME =your_neo4j_user
   NEO4J_PASSWORD=your_neo4j_password
   ```
3. **Run**:
   Ensure you are in the root directory of the project and then run:

   ```sh
   docker build -t app .
   docker run app
   ```

   This will build the Docker image and run the container, exposing the application on port 5000.

# Another Alternative, you can use Docker compose file to run the applicaton:
  - Build and start the services with Docker Compose:

    ```bash
    docker-compose up --build
    ```
   This command will build the Flask app's Docker image, set up MongoDB with data persistence, and configure Caddy as the reverse proxy.
   
   ### Accessing the Application

      - Flask App: Access the application through Caddy on http://localhost:5000.

   ### Stopping the Services

      To stop the services, use:

      ```bash
      docker-compose down