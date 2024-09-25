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
5. **Setup Required Folders**:
   Ensure the following folders are present in the root directory and contain the necessary data:

   metta_data: Folder for storing Metta data.
   cypher_data: Folder for storing Neo4j data.

6. **Choose Your Database Type**
   In the config directory modify config.yaml to change between databses.

   - To use Metta, set the type to 'metta'.
   - To use Neo4j, set the type to 'cypher'.

   Example

   ```config
   database
    type = cypher  # Change to 'metta' if needed
   ```

7. **Set Graph Query Limit**
   In the config directory modify config.yaml to change the maximum number of nodes to return while relevant information is returned without truncating the result. if the limit is set to 'None' it will return the full result

   Example

   ```config
   graph:
       limit = 100 #set the maximum number of nodes to return
   ```

8. **Run the Application**:
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
