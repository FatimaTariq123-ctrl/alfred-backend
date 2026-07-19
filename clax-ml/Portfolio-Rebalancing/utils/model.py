import torch
import torch.nn as nn

class LSTMRegressor(nn.Module):
    def __init__(self, input_size, hidden_layer_size=300, output_size=1):
        super(LSTMRegressor, self).__init__()
        self.hidden_layer_size = hidden_layer_size
        
        # LSTM(300) -> LSTM(300) -> Dense(100) layers.
        self.lstm1 = nn.LSTM(input_size, hidden_layer_size, batch_first=True)
        self.lstm2 = nn.LSTM(hidden_layer_size, hidden_layer_size, batch_first=True)
        
        # Dense(100) layer with ReLU
        self.linear1 = nn.Linear(hidden_layer_size, 100)
        self.relu = nn.ReLU()
        
        # Output layer: Dense(num_assets) with Softmax
        self.linear2 = nn.Linear(100, output_size)
        self.softmax = nn.Softmax(dim=1) # Softmax across the output features (weights)

    def forward(self, input_seq):
        # input_seq: (batch_size, seq_len, input_size)
        
        lstm_out1, _ = self.lstm1(input_seq)
        lstm_out2, _ = self.lstm2(lstm_out1)
        
        # Take the output of the last time step
        last_time_step_out = lstm_out2[:, -1, :]
        
        # Dense(100) -> ReLU
        dense1_out = self.relu(self.linear1(last_time_step_out))
        
        # Dense(output_size) -> Softmax
        output = self.softmax(self.linear2(dense1_out))
        
        return output

class RMSELoss(nn.Module):
    def __init__(self):
        super().__init__()
        self.mse = nn.MSELoss()

    def forward(self, yhat, y):
        # Ensure yhat and y have the same shape for MSE
        return torch.sqrt(self.mse(yhat, y))