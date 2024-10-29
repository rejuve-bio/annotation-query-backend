import logging
from flask_mail import Mail, Message
import pandas as pd
from pathlib import Path
import datetime
import os

mail = None

def init_mail(app):
    global mail
    mail = Mail(app)

def convert_to_csv(response):
    file_name = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '.xls'
    file_path = Path(f'./{file_name}').resolve()
    
    nodes, edges = response
    # Convert nodes and edges to DataFrames
    # Add sheet for each node
    # Convert to .xls file so that there is separate sheet for nodes and edges in a single file
    try:
        with pd.ExcelWriter(file_path) as writer:
            for key, _ in nodes.items():
                node = pd.json_normalize(nodes[key])
                node.columns = [col.replace('data.', '') for col in node.columns] 
                node.to_excel(writer, sheet_name=f'{key}', index=False)
            for key, _ in edges.items():
                source = edges[key][0]['data']['source'].split(' ')[0]
                target = edges[key][0]['data']['target'].split(' ')[0]
                edge = pd.json_normalize(edges[key])
                edge.columns = [col.replace('data.', '') for col in edge.columns]
                edge.to_excel(writer, sheet_name=f'{source}-relationship-{target}', index=False)
    except Exception as e:
        os.remove(file_path)
        logging.error(e)
    return file_path

def send_email(subject, recipients, body, response):
    attachment_path = None
    try:
        if mail is None:
            raise Exception("Can't send email")
        
        # Create the email message
        msg = Message(
            subject=subject,
            recipients=recipients,
            body=body,
        )
        
        attachment_path = convert_to_csv(response)

        if attachment_path:
            with open(attachment_path, 'rb') as f:
                file_data = f.read()
                file_name = attachment_path.name # Get the file name from the path
                msg.attach(file_name, 'application/octet-stream', file_data)

        # Send the email
        mail.send(msg)
        logging.info("Email sent successfully!")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
    finally:
        if attachment_path:
            os.remove(attachment_path)

