### Annotaion Service

backend API.

*Supported OS:* **Linux & Mac**

## Prerequisites

- Docker
- Neo4j or Neo4j Aura account

**Follow these steps to run :**

1. **Clone the Repository**:
    ```sh
    git clone https://github.com/eyasubirhanu/annotation-query-backend.git
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
    NEO4J_USER=your_neo4j_user
    NEO4J_PASSWORD=your_neo4j_password
    ```
5. **Setup Required Folders**:
    Ensure you have the following folders in the root directory:

    metta_data: This folder is for Metta data.
    cypher_data: This folder is for Neo4j data.

6. **Choose Your Database Type**
   In the config directory mofidy config.ini to change between databses.

   - To use Metta, set the type to 'metta'.
   - To use Neo4j, set the type to 'cypher'.

Example

   ```config   
   [database]
   type = cypher  # Change to 'metta' if needed
   ```

7. **Run the Application**:
    ```sh
    flask run
    ```
# Alternatively, you can use Docker to run the application:
**Build and Run the Docker Container**

   Ensure you are in the root directory of the project and then run:

   ```sh
   docker build -t app .
   docker run app
   ```

   This will build the Docker image and run the container, exposing the application on port 5000.

Notes:

    If you choose the Docker approach, you can skip the steps for setting up the virtual environment and installing dependencies manually.
    Ensure that the .env file is located in the root directory for Docker to use it correctly.

    