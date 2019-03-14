import torch
import torch.nn as nn
from modelling.util import initialize_weights
from modelling.clstm import CLSTM

class VectorAtt(nn.Module):
    
    def __init__(self, hidden_dim_size):
        """
            Assumes input will be in the form (batch, time_steps, hidden_dim_size, height, width)
            Returns reweighted hidden states.
        """
        super(VectorAtt, self).__init__()
        self.linear = nn.Linear(hidden_dim_size, 1, bias=False)
        nn.init.constant_(self.linear.weight, 1)
        self.softmax = nn.Softmax(dim=1)
        
    def forward(self, hidden_states):
        print(self.linear.weight)
        hidden_states = hidden_states.permute(0, 1, 3, 4, 2).contiguous() # puts channels last
        reweighted = self.softmax(self.linear(hidden_states)) * hidden_states
        return reweighted.permute(0, 1, 4, 2, 3).contiguous()

class TemporalAtt(nn.Module):

    def __init__(self, hidden_dim_size, d, r):
        """
            Assumes input will be in the form (batch, time_steps, hidden_dim_size, height, width)
            Returns reweighted timestamps.
        """
        super(TemporalAtt, self).__init__()
        self.w_s1 = nn.Linear(in_features=hidden_dim_size, out_features=d, bias=False) 
        self.w_s2 = nn.Linear(in_features=d, out_features=r, bias=False) 
        nn.init.constant_(self.w_s1.weight, 1)
        nn.init.constant_(self.w_s2.weight, 1)
        self.tanh = nn.Tanh()
        self.softmax = nn.Softmax(dim=1)

    def forward(self, hidden_states):
        hidden_states = hidden_states.permute(0, 1, 3, 4, 2).contiguous()
        z1 = self.tanh(self.w_s1(hidden_states))
        attn_weights = self.softmax(self.w_s2(z1))
        reweighted = attn_weights * hidden_states
        return reweighted.permute(0, 1, 4, 2, 3).contiguous()

class CLSTMSegmenter(nn.Module):
    """ CLSTM followed by conv for segmentation output
    """

    def __init__(self, input_size, hidden_dims, lstm_kernel_sizes, 
                 conv_kernel_size, lstm_num_layers, num_classes, bidirectional,
                 avg_hidden_states, early_feats, batch_size):

        super(CLSTMSegmenter, self).__init__()
        self.early_feats = early_feats
        self.input_size = input_size
        self.batch_size = batch_size
        d_attn_dim = 128
        r_attn_dim = 1

        if not isinstance(hidden_dims, list):
            hidden_dims = [hidden_dims]        

        self.clstm = CLSTM(input_size, hidden_dims, lstm_kernel_sizes, lstm_num_layers)
        
        self.bidirectional = bidirectional
        if self.bidirectional:
            self.clstm_rev = CLSTM(input_size, hidden_dims, lstm_kernel_sizes, lstm_num_layers)
            self.att_rev = VectorAtt(hidden_dims[-1])
            #self.att_rev = TemporalAtt(hidden_dims[-1], d_attn_dim, r_attn_dim)
        self.avg_hidden_states = avg_hidden_states
        
        in_channels = hidden_dims[-1] if not self.bidirectional else hidden_dims[-1] * 2
        self.conv = nn.Conv2d(in_channels=in_channels, out_channels=num_classes, kernel_size=conv_kernel_size, padding=int((conv_kernel_size - 1) / 2))
        
        self.logsoftmax = nn.LogSoftmax(dim=1) 
        initialize_weights(self)
       
        #self.att1 = TemporalAtt(hidden_dims[-1], d_attn_dim, r_attn_dim)
        self.att1 = VectorAtt(hidden_dims[-1])        
#         self.att2 = VectorAtt(hidden_dims[-1])

        
    def forward(self, inputs):
        layer_outputs, last_states = self.clstm(inputs)
        final_state = torch.sum(self.att1(layer_outputs), dim=1)#, torch.sum(self.att2(layer_outputs), dim=1), dim=1) 
        #final_state = last_states[0] if not self.avg_hidden_states else torch.mean(layer_outputs, dim=1)
        if self.bidirectional:
            rev_inputs = torch.flip(inputs, dims=[1])
            rev_layer_outputs, rev_last_states = self.clstm_rev(rev_inputs)
            final_state_rev = torch.sum(self.att_rev(rev_layer_outputs), dim=1)
            final_state = torch.cat([final_state, final_state_rev], dim=1)
        scores = self.conv(final_state)
        
        output = scores if self.early_feats else self.logsoftmax(scores)
        return output
        
