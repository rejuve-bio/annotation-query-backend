import os
from dotenv import load_dotenv
from app.services.llm_models import OpenAIModel, GeminiModel
from app.services.graph_handler import GraphSummarizer
load_dotenv()

class LLMHandler:
    def __init__(self):
        model_type = os.getenv('LLM_MODEL')

        if model_type == 'openai':
            openai_api_key = os.getenv('OPENAI_API_KEY')
            if not openai_api_key:
                raise ValueError("OpenAI API key not found")
            self.model = OpenAIModel(openai_api_key)
        elif model_type == 'gemini':
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if not gemini_api_key:
                raise ValueError("Gemini API key not found")
            self.model = GeminiModel(gemini_api_key)
        else:
            raise ValueError("Invalid model type in configuration")

    def generate_title(self, query):
        prompt = f'''From this query generate approperiate title
                     Query: {query}'''
        title = self.model.generate(prompt)
        return title

    def generate_summary(self, graph):
        summarizer = GraphSummarizer(self.model)
        summary = summarizer.ai_summarizer(graph)
        return summary
