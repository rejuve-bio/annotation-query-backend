SUMMARY_PROMPT_BASED_ON_USER_QUERY = """
                                    ## **System Instruction**  
                                    You are an intelligent assistant tasked with generating a natural language response to a user's question. Use the provided user question and retrieved graph (in JSON format) to craft a clear, concise, and accurate answer. If the graph does not contain enough information, explain this to the user.  
                                    
                                    ---
                                    
                                    ### **User Question**  
                                    `{user_query}` 
                                    
                                    ### **Retrieved Graph (JSON)**  
                                    ```json
                                    {description}
                                """
SUMMARY_PROMPT_CHUNKING = """
                You are an expert biology assistant on summarizing graph data.\n\n
                Given the following graph data:\n{description}\n\n
                Given the following previous summary:\n{prev_summery}\n\n"
                Your task is to analyze the graph ,including the previous summary and summarize the most important trends, patterns, and relationships.\n
                Instructions:\n
                  - Count and list important metrics, such as the number of nodes and edges.    
                  - Identify any central nodes and explain their role in the network.     
                  - Mention any notable structures in the graph, such as chains, hubs, or clusters.      
                  - Discuss any specific characteristics of the data, such as alternative splicing or regulatory mechanisms that may be involved.     
                  - Format the response clearly and concisely.\n\n
                Count and list important metrics
                Identify any central nodes or relationships and highlight any important patterns.
                Also, mention key relationships between nodes and any interesting structures (such as chains or hubs).
                Please provide a summary based solely on the graph information.
                Addressed points in a separate paragraph, with clear and concise descriptions. Make sure not to use bullet points or numbered lists, but instead focus on delivering the content in paragraph form.
 """
SUMMARY_PROMPT_CHUNKING_USER_QUERY ="""
                ## **System Instruction**  
                You are an intelligent assistant tasked with answering a user's question by processing graph data in chunks. Use the **previous response** as context and integrate information from the **current graph chunk** to craft a clear and complete answer.  

                ### **Key Requirements**  
                1. Maintain continuity with the **previous response**.  
                2. Incorporate new, relevant information from the **current graph chunk**.  
                3. Ensure the response is concise and directly addresses the user's question without unnecessary information.  

                ---

                ### **Input**

                #### **User Question**  
                `{user_query}`  

                #### **Previous Response**  
                `{prev_summery}`  

                #### **Current Graph Chunk (JSON)**  
                ```json
                {description}
"""
SUMMARY_PROMPT = """
You are an expert biology assistant on summarizing graph data.

Given the following graph data:
{description}

Your task is to analyze and summarize the most important trends, patterns, and relationships in a list of paragraphs. 
Each paragraph should address one of the following points:
- Identify key trends and relationships in the graph data.
- Count and list important metrics, such as the number of nodes and edges.
- Identify any central nodes and explain their role in the network.
- Mention any notable structures in the graph, such as chains, hubs, or clusters.
- Discuss any specific characteristics of the data, such as alternative splicing or regulatory mechanisms that may be involved.
- Explain any notable relationships, including nodes that have a higher number of associated related nodes or complex processes.
Addressed points in a separate paragraph, with clear and concise descriptions. Make sure not to use bullet points or numbered lists, but instead focus on delivering the content in paragraph form.
"""