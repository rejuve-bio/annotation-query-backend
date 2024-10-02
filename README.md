### Annotaion Service

backend API.

_Supported OS:_ **Linux & Mac**

## Prerequisites

- Docker
- Neo4j or Neo4j Aura account

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

8. **Set Graph Query Limit**
   In the config directory modify config.yaml to change the maximum number of nodes to return while relevant information is returned without truncating the result. if the limit is set to 'None' it will return the full result

   Example

   ```config
   graph:
       limit = 100 #set the maximum number of nodes to return
   ```

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
