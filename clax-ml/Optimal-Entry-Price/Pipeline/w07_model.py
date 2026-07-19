# utils/model.py

import torch
import torch.nn as nn

class LSTMRegressor(nn.Module):
    def __init__(self, input_dim, hidden_dim1=300, hidden_dim2=300, dense_dim=100):
        super().__init__()
        self.lstm1 = nn.LSTM(input_dim, hidden_dim1, batch_first=True)
        self.lstm2 = nn.LSTM(hidden_dim1, hidden_dim2, batch_first=True)
        self.dense1 = nn.Linear(hidden_dim2, dense_dim)
        self.relu = nn.ReLU()
        self.dense2 = nn.Linear(dense_dim, 1)

    def forward(self, x):
        lstm_out1, _ = self.lstm1(x)
        lstm_out2, _ = self.lstm2(lstm_out1)
        # We only need the output of the last time step
        last_time_step_out = lstm_out2[:, -1, :]
        x = self.relu(self.dense1(last_time_step_out))
        x = self.dense2(x)
        return x

class RMSELoss(nn.Module):
    def __init__(self):
        super().__init__()
        self.mse = nn.MSELoss()

    def forward(self, yhat, y):
        return torch.sqrt(self.mse(yhat, y))


def apply_directional_activation(pred: torch.Tensor, direction: torch.Tensor) -> torch.Tensor:
    """
    Apply sign constraints based on trade direction.
    direction: 1 for buy (non-negative), 0 for sell (non-positive).
    """
    if direction.dim() == 1:
        direction = direction.unsqueeze(1)
    buy_mask = direction >= 0.5
    pos = torch.relu(pred)
    neg = -torch.abs(pred)
    return torch.where(buy_mask, pos, neg)
