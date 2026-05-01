import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer
from torch.utils.data import Dataset
import re


class IntentDataset(Dataset):
    """
    Dataset for handling student input and session context for 5-class intent categorization.
    """
    def __init__(self, data, tokenizer, max_length=128):
        # data: list of dicts with 'student_input', 'session_context', 'label'
        self.data = data
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.label_map = {
            'On-Topic Question': 0,
            'Off-Topic Question': 1,
            'Emotional-State': 2,
            'Pace-Related': 3,
            'Repeat/clarification': 4
        }
    
    def __len__(self):
        return len(self.data)
    
    def __getitem__(self, idx):
        item = self.data[idx]
        student_input = str(item.get('student_input', ''))
        session_context = str(item.get('session_context', ''))
        
        # Tokenize pair — longest_first truncation preserves student input priority
        encoded = self.tokenizer(
            student_input,
            session_context,
            padding='max_length',
            truncation='longest_first',
            max_length=self.max_length,
            return_tensors='pt'
        )
        
        label_val = item.get('label', 0)
        if isinstance(label_val, str):
            label_val = self.label_map.get(label_val, 0)
            
        output = {
            'input_ids': encoded['input_ids'].squeeze(0),
            'attention_mask': encoded['attention_mask'].squeeze(0),
            'labels': torch.tensor(label_val, dtype=torch.long)
        }
        if 'token_type_ids' in encoded:
            output['token_type_ids'] = encoded['token_type_ids'].squeeze(0)
            
        return output


class CompoundSentenceSplitter:
    """
    Algorithm to split compound sentences containing 2 separate questions.
    Handles various patterns and conjunctions commonly used to combine questions.
    English only.
    """
    
    def __init__(self):
        # English question words
        self.question_words = [
            'what', 'when', 'where', 'which', 'who', 'whom', 'whose', 'why', 'how',
            'is', 'are', 'was', 'were', 'do', 'does', 'did', 'can', 'could', 
            'will', 'would', 'should', 'may', 'might', 'must'
        ]
        
        # English conjunctions
        self.conjunctions = [
            'and', 'or', 'also', 'plus', 'additionally', 'moreover'
        ]
        
        # English transition phrases
        self.transition_phrases = [
            'and also', 'and what about', 'and how about', 'or what about', 
            'or how about', 'also what', 'also how', 'also when', 'also where',
            'also who', 'also why', 'plus what', 'plus how'
        ]
    
    def split_compound_question(self, text):
        """
        Split a compound sentence into 2 separate questions if applicable.
        Works with English text.
        
        Args:
            text (str): Input text that may contain compound questions
            
        Returns:
            list: List of separated questions. Returns [text] if no split is needed.
        """
        text = text.strip()
        
        # Check if text is likely a question
        if not self._is_question(text):
            return [text]
        
        # Try different splitting strategies
        questions = []
        
        # Strategy 1: Split by transition phrases
        questions = self._split_by_transition_phrases(text)
        if len(questions) > 1:
            return self._clean_questions(questions)
        
        # Strategy 2: Split by conjunction followed by question word
        questions = self._split_by_conjunction_pattern(text)
        if len(questions) > 1:
            return self._clean_questions(questions)
        
        # Strategy 3: Split by semicolon or comma-conjunction pattern
        questions = self._split_by_punctuation_pattern(text)
        if len(questions) > 1:
            return self._clean_questions(questions)
        
        # Strategy 4: Split by multiple question marks
        questions = self._split_by_question_marks(text)
        if len(questions) > 1:
            return self._clean_questions(questions)
        
        # No split found, return original
        return [text]
    
    def _is_question(self, text):
        """Check if text is likely a question (English)"""
        text_stripped = text.strip()
        
        # Has question mark
        if '?' in text:
            return True
        
        # Check for question words at the start
        words = text_stripped.split()
        if words:
            first_word = words[0].lower()
            # Check English question words
            if first_word in self.question_words:
                return True
        
        return False
    
    def _split_by_transition_phrases(self, text):
        """Split by transition phrases (English)"""
        for phrase in self.transition_phrases:
            # English phrase with word boundaries
            pattern = r'\s+' + re.escape(phrase) + r'\s+'
            
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) == 2 and parts[0] and parts[1]:
                    return parts
        
        return [text]
    
    def _split_by_conjunction_pattern(self, text):
        """Split by conjunction followed by question word (English)"""
        # Pattern: conjunction + question word
        for conj in self.conjunctions:
            for qword in self.question_words:
                # English pattern with word boundaries
                pattern = r'\s+' + re.escape(conj) + r'\s+' + re.escape(qword) + r'\b'
                
                match = re.search(pattern, text, re.IGNORECASE)
                
                if match:
                    # Find the actual position in original text
                    split_pos = match.start()
                    part1 = text[:split_pos].strip()
                    part2 = text[split_pos:].strip()
                    
                    # Remove leading conjunction from part2
                    for c in self.conjunctions:
                        is_arabic_c = any(ch in 'أبتثجحخدذرزسشصضطظعغفقكلمنهويىةؤإآ' for ch in c)
                        part2 = re.sub(r'^\s*' + re.escape(c) + r'\s+', '', part2, flags=re.IGNORECASE if not is_arabic_c else 0)
                    
                    # Ensure both parts are questions
                    if part1 and part2 and self._is_question(part1):
                        return [part1, part2]
        
        return [text]
    
    def _split_by_punctuation_pattern(self, text):
        """Split by semicolon or specific comma patterns"""
        # Split by semicolon (works for both languages)
        if ';' in text or '؛' in text:  # Added Arabic semicolon
            parts = re.split(r'[;؛]', text, maxsplit=1)
            if len(parts) == 2:
                parts = [p.strip() for p in parts]
                if all(self._is_question(p) for p in parts):
                    return parts
        
        # Split by comma followed by question word
        pattern = r',\s+(?=' + '|'.join([re.escape(qw) for qw in self.question_words]) + r')'
        parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE)
        
        if len(parts) == 2:
            parts = [p.strip() for p in parts]
            # Only split if second part is clearly a question
            if self._is_question(parts[1]):
                return parts
        
        return [text]
    
    def _split_by_question_marks(self, text):
        """Split by question marks if multiple exist (both ? and ؟)"""
        # Count both English and Arabic question marks
        q_marks = text.count('?') + text.count('؟')
        
        if q_marks >= 2:
            # Split at first question mark
            match = re.search(r'[?؟]', text)
            if match:
                split_pos = match.end()
                part1 = text[:split_pos].strip()
                part2 = text[split_pos:].strip()
                
                if part2:  # Ensure second part is not empty
                    return [part1, part2]
        
        return [text]
    
    def _clean_questions(self, questions):
        """Clean and validate split questions"""
        cleaned = []
        
        for q in questions:
            q = q.strip()
            
            # Skip empty questions
            if not q:
                continue
            
            # Ensure question ends with '?' or '؟' if it's clearly a question
            if self._is_question(q):
                # Check if already has question mark
                if not (q.endswith('?') or q.endswith('؟')):
                    # Add appropriate question mark based on language
                    if any(c in 'أبتثجحخدذرزسشصضطظعغفقكلمنهويىةؤإآ' for c in q):
                        q += '؟'  # Arabic question mark
                    else:
                        q += '?'  # English question mark
            
            cleaned.append(q)
        
        return cleaned if len(cleaned) > 1 else [' '.join(questions)]


class TinyBertCNN(nn.Module):
    """
    TinyBERT-CNN model for intent classification.
    Combines TinyBERT embeddings with CNN layers + BatchNorm + hidden FC layer.
    """
    
    def __init__(
        self,
        num_classes,
        bert_model_name='distilbert-base-uncased',
        num_filters=256,
        filter_sizes=[2, 3, 4],
        dropout=0.5,
        hidden_dim=128,
        freeze_bert=False
    ):
        """
        Args:
            num_classes (int): Number of intent classes
            bert_model_name (str): Pre-trained TinyBERT model name
            num_filters (int): Number of filters for each filter size
            filter_sizes (list): List of filter sizes for CNN
            dropout (float): Dropout rate
            hidden_dim (int): Hidden FC layer dimension
            freeze_bert (bool): Whether to freeze BERT parameters
        """
        super(TinyBertCNN, self).__init__()
        
        # Load TinyBERT model
        self.bert = AutoModel.from_pretrained(bert_model_name)
        self._supports_token_type_ids = (
            hasattr(self.bert.config, 'type_vocab_size') and
            self.bert.config.type_vocab_size > 1
        )
        self.bert_hidden_size = self.bert.config.hidden_size
        
        # Freeze BERT parameters if specified
        if freeze_bert:
            for param in self.bert.parameters():
                param.requires_grad = False
        
        # CNN layers with BatchNorm
        self.convs = nn.ModuleList([
            nn.Conv1d(
                in_channels=self.bert_hidden_size,
                out_channels=num_filters,
                kernel_size=fs
            )
            for fs in filter_sizes
        ])
        self.batchnorms = nn.ModuleList([
            nn.BatchNorm1d(num_filters)
            for _ in filter_sizes
        ])
        
        # Dropout
        self.dropout = nn.Dropout(dropout)
        
        # Hidden FC layer
        cnn_out_dim = len(filter_sizes) * num_filters
        self.fc_hidden = nn.Linear(cnn_out_dim, hidden_dim)
        self.bn_hidden = nn.BatchNorm1d(hidden_dim)
        
        # Output layer
        self.fc = nn.Linear(hidden_dim, num_classes)
        
    def forward(self, input_ids, attention_mask, token_type_ids=None):
        """
        Forward pass
        
        Args:
            input_ids: Token IDs (batch_size, seq_len)
            attention_mask: Attention mask (batch_size, seq_len)
            token_type_ids: Token type IDs (batch_size, seq_len), optional
            
        Returns:
            logits: Classification logits (batch_size, num_classes)
        """
        # Get TinyBERT embeddings
        # outputs: (batch_size, seq_len, hidden_size)
        bert_kwargs = {
            'input_ids': input_ids,
            'attention_mask': attention_mask
        }
        if token_type_ids is not None and self._supports_token_type_ids:
            bert_kwargs['token_type_ids'] = token_type_ids
            
        bert_output = self.bert(**bert_kwargs)
        
        # Use last hidden state
        # sequence_output: (batch_size, seq_len, hidden_size)
        sequence_output = bert_output.last_hidden_state
        
        # Transpose for CNN: (batch_size, hidden_size, seq_len)
        sequence_output = sequence_output.transpose(1, 2)
        
        # Pad if sequence is shorter than the largest kernel
        max_kernel = max(conv.kernel_size[0] for conv in self.convs)
        if sequence_output.size(2) < max_kernel:
            pad_size = max_kernel - sequence_output.size(2)
            sequence_output = torch.nn.functional.pad(sequence_output, (0, pad_size))
        
        # Apply convolution + batchnorm + max pooling for each filter size
        conv_outputs = []
        for conv, bn in zip(self.convs, self.batchnorms):
            # conv_out: (batch_size, num_filters, seq_len - filter_size + 1)
            conv_out = torch.relu(bn(conv(sequence_output)))
            # pooled: (batch_size, num_filters)
            pooled = torch.max_pool1d(conv_out, conv_out.size(2)).squeeze(2)
            conv_outputs.append(pooled)
        
        # Concatenate all features
        # concatenated: (batch_size, len(filter_sizes) * num_filters)
        concatenated = torch.cat(conv_outputs, dim=1)
        concatenated = self.dropout(concatenated)
        
        # Hidden FC layer
        hidden = torch.relu(self.bn_hidden(self.fc_hidden(concatenated)))
        hidden = self.dropout(hidden)
        
        # Final classification
        logits = self.fc(hidden)
        
        return logits


class IntentClassifier:
    """
    Wrapper class for training and inference
    """
    
    def __init__(
        self,
        num_classes,
        bert_model_name='distilbert-base-uncased',
        num_filters=256,
        filter_sizes=[2, 3, 4],
        dropout=0.5,
        freeze_bert=False,
        device=None
    ):
        self.device = device or torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Initialize model
        self.model = TinyBertCNN(
            num_classes=num_classes,
            bert_model_name=bert_model_name,
            num_filters=num_filters,
            filter_sizes=filter_sizes,
            dropout=dropout,
            freeze_bert=freeze_bert
        ).to(self.device)
        
        # Initialize tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(bert_model_name)
        
        # Initialize compound sentence splitter
        self.sentence_splitter = CompoundSentenceSplitter()
        
        self.num_classes = num_classes
        
    def preprocess_text(self, text):
        """
        Preprocess text by splitting compound questions if detected
        
        Args:
            text (str): Input text (English or Arabic)
            
        Returns:
            list: List of individual questions
        """
        return self.sentence_splitter.split_compound_question(text)
    
    def predict(self, student_inputs, session_contexts=None, max_length=128, split_compound=False):
        """
        Predict intents for input texts
        
        Args:
            student_inputs (list): List of student input texts (English or Arabic)
            session_contexts (list): List of session context texts
            max_length (int): Maximum sequence length
            split_compound (bool): Whether to split compound questions before prediction
            
        Returns:
            If split_compound=False:
                predictions: Predicted class indices
                probabilities: Prediction probabilities
            If split_compound=True:
                predictions: List of predictions (may contain multiple per text if split)
                probabilities: List of probabilities
                split_info: Dictionary with information about splits
        """
        # Handle compound questions if requested
        if split_compound:
            return self._predict_with_splitting(student_inputs, session_contexts, max_length)
        
        self.model.eval()
        
        # Determine if we are passing single string or pair
        if session_contexts is not None:
            text_args = (student_inputs, session_contexts)
        else:
            text_args = (student_inputs,)
        
        # Tokenize
        encoded = self.tokenizer(
            *text_args,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors='pt'
        )
        
        input_ids = encoded['input_ids'].to(self.device)
        attention_mask = encoded['attention_mask'].to(self.device)
        token_type_ids = encoded.get('token_type_ids')
        if token_type_ids is not None:
            token_type_ids = token_type_ids.to(self.device)
        
        with torch.no_grad():
            logits = self.model(input_ids, attention_mask, token_type_ids=token_type_ids)
            probabilities = torch.softmax(logits, dim=1)
            predictions = torch.argmax(probabilities, dim=1)
        
        return predictions.cpu().numpy(), probabilities.cpu().numpy()
    
    def _predict_with_splitting(self, student_inputs, session_contexts=None, max_length=128):
        """
        Predict intents after splitting compound questions (English and Arabic)
        
        Args:
            student_inputs (list): List of input texts
            session_contexts (list): List of session context texts
            max_length (int): Maximum sequence length
            
        Returns:
            predictions: List of predictions (one per original text, may contain multiple if split)
            probabilities: List of probabilities
            split_info: Dictionary with information about splits
        """
        all_predictions = []
        all_probabilities = []
        split_info = {
            'original_texts': student_inputs,
            'split_texts': [],
            'was_split': [],
            'split_indices': []  # Maps split question index to original text index
        }
        
        # Collect all questions after splitting
        all_questions = []
        all_contexts = []
        for i, text in enumerate(student_inputs):
            questions = self.preprocess_text(text)
            split_info['split_texts'].append(questions)
            split_info['was_split'].append(len(questions) > 1)
            
            # Track which original text each split question belongs to
            for _ in questions:
                split_info['split_indices'].append(i)
                if session_contexts is not None:
                    all_contexts.append(session_contexts[i])
            
            all_questions.extend(questions)
        
        # Predict for all questions at once
        if all_questions:
            contexts_to_pass = all_contexts if session_contexts is not None else None
            predictions, probabilities = self.predict(all_questions, contexts_to_pass, max_length, split_compound=False)
            
            # Reorganize results by original text
            idx = 0
            for i, text in enumerate(student_inputs):
                num_questions = len(split_info['split_texts'][i])
                text_predictions = predictions[idx:idx + num_questions]
                text_probabilities = probabilities[idx:idx + num_questions]
                
                all_predictions.append(text_predictions)
                all_probabilities.append(text_probabilities)
                
                idx += num_questions
        
        return all_predictions, all_probabilities, split_info
    
    def train_step(self, batch, optimizer, criterion):
        """
        Single training step
        
        Args:
            batch: Dictionary with 'input_ids', 'attention_mask', 'labels'
            optimizer: Optimizer
            criterion: Loss function
            
        Returns:
            loss: Training loss
        """
        self.model.train()
        
        input_ids = batch['input_ids'].to(self.device)
        attention_mask = batch['attention_mask'].to(self.device)
        labels = batch['labels'].to(self.device)
        token_type_ids = batch.get('token_type_ids')
        if token_type_ids is not None:
            token_type_ids = token_type_ids.to(self.device)
        
        # Forward pass
        logits = self.model(input_ids, attention_mask, token_type_ids=token_type_ids)
        loss = criterion(logits, labels)
        
        # Backward pass
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        
        return loss.item()
    
    def evaluate(self, dataloader, criterion):
        """
        Evaluate model on validation/test set
        
        Args:
            dataloader: DataLoader for evaluation
            criterion: Loss function
            
        Returns:
            avg_loss: Average loss
            accuracy: Classification accuracy
        """
        self.model.eval()
        
        total_loss = 0
        total_correct = 0
        total_samples = 0
        
        with torch.no_grad():
            for batch in dataloader:
                input_ids = batch['input_ids'].to(self.device)
                attention_mask = batch['attention_mask'].to(self.device)
                labels = batch['labels'].to(self.device)
                token_type_ids = batch.get('token_type_ids')
                if token_type_ids is not None:
                    token_type_ids = token_type_ids.to(self.device)
                
                # Forward pass
                logits = self.model(input_ids, attention_mask, token_type_ids=token_type_ids)
                loss = criterion(logits, labels)
                
                # Calculate metrics
                predictions = torch.argmax(logits, dim=1)
                total_loss += loss.item() * labels.size(0)
                total_correct += (predictions == labels).sum().item()
                total_samples += labels.size(0)
        
        avg_loss = total_loss / total_samples
        accuracy = total_correct / total_samples
        
        return avg_loss, accuracy
    
    def save_model(self, path):
        """Save model checkpoint"""
        torch.save({
            'model_state_dict': self.model.state_dict(),
            'num_classes': self.num_classes
        }, path)
        print(f"Model saved to {path}")
    
    def load_model(self, path):
        """Load model checkpoint"""
        checkpoint = torch.load(path, map_location=self.device)
        self.model.load_state_dict(checkpoint['model_state_dict'])
        print(f"Model loaded from {path}")

