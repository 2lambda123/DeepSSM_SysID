import torch
import torch.nn as nn
import torch.distributions as tdist

"""VRNN-Gauss-I 
modification of the VRNN-Gauss without the conditional prior. 
VRNN-Gauss uses zt~N(mu,sigma) with [mu,sigma]=NN(h[t])
VRNN-Gauss-I uses zt~N(0,1)"""


class VRNN_Gauss_I(nn.Module):
    def __init__(self, param, device, bias=False):
        super(VRNN_Gauss_I, self).__init__()

        self.y_dim = param.y_dim
        self.u_dim = param.u_dim
        self.h_dim = param.h_dim
        self.z_dim = param.z_dim
        self.n_layers = param.n_layers
        self.device = device

        # feature-extracting transformations (phi_y, phi_u and phi_z)
        self.phi_y = nn.Sequential(
            nn.Linear(self.y_dim, self.h_dim),
            nn.ReLU(),
            nn.Linear(self.h_dim, self.h_dim),)
        self.phi_u = nn.Sequential(
            nn.Linear(self.u_dim, self.h_dim),
            nn.ReLU(),
            nn.Linear(self.h_dim, self.h_dim),)
        self.phi_z = nn.Sequential(
            nn.Linear(self.z_dim, self.h_dim),
            nn.ReLU(),
            nn.Linear(self.h_dim, self.h_dim),)

        # encoder function (phi_enc) -> Inference
        self.enc = nn.Sequential(
            nn.Linear(self.h_dim + self.h_dim, self.h_dim),
            nn.ReLU(),
            nn.Linear(self.h_dim, self.h_dim),
            nn.ReLU())
        self.enc_mean = nn.Sequential(
            nn.Linear(self.h_dim, self.z_dim))
        self.enc_logvar = nn.Sequential(
            nn.Linear(self.h_dim, self.z_dim),
            nn.ReLU())

        # decoder function (phi_dec) -> Generation
        self.dec = nn.Sequential(
            nn.Linear(self.h_dim + self.h_dim, self.h_dim),
            nn.ReLU(),
            nn.Linear(self.h_dim, self.h_dim),
            nn.ReLU())
        self.dec_mean = nn.Sequential(
            nn.Linear(self.h_dim, self.y_dim),
        )
        self.dec_logvar = nn.Sequential(
            nn.Linear(self.h_dim, self.y_dim),
            nn.ReLU())

        # recurrence function (f_theta) -> Recurrence
        self.rnn = nn.GRU(self.h_dim + self.h_dim, self.h_dim, self.n_layers, bias)

    def forward(self, u, y):
        #  batch size
        batch_size = y.shape[0]
        seq_len = y.shape[2]
        # allocation
        loss = 0
        KLD_total = 0
        # initialization
        h = torch.zeros(self.n_layers, batch_size, self.h_dim, device=self.device)

        # constant so can be outside of loop
        # prior: z_t ~ N(0,1) (for KLD loss)
        prior_mean_t = torch.zeros([batch_size, self.z_dim], device=self.device)
        prior_logvar_t = torch.zeros([batch_size, self.z_dim], device=self.device)

        # for all time steps
        for t in range(seq_len):
            # feature extraction: y_t
            phi_y_t = self.phi_y(y[:, :, t])
            # feature extraction: u_t
            phi_u_t = self.phi_u(u[:, :, t])

            # encoder: y_t, h_t -> z_t
            enc_t = self.enc(torch.cat([phi_y_t, h[-1]], 1))
            enc_mean_t = self.enc_mean(enc_t)
            enc_logvar_t = self.enc_logvar(enc_t)

            """# prior: z_t ~ N(0,1) (for KLD loss)
            prior_mean_t = torch.zeros_like(enc_mean_t)
            prior_logvar_t = torch.zeros_like(enc_mean_t)"""

            # sampling and reparameterization: get a new z_t
            temp = tdist.Normal(enc_mean_t, enc_logvar_t.exp().sqrt())
            z_t = tdist.Normal.rsample(temp)
            # z_t = self._reparameterized_sample(prior_mean_t, prior_logvar_t)
            # feature extraction: z_t
            phi_z_t = self.phi_z(z_t)

            # decoder: h_t, z_t -> y_t
            dec_t = self.dec(torch.cat([phi_z_t, h[-1]], 1))
            dec_mean_t = self.dec_mean(dec_t)
            dec_logvar_t = self.dec_logvar(dec_t)
            # sample = self._reparameterized_sample(dec_mean_t, dec_logvar_t)
            pred_dist = tdist.Normal(dec_mean_t, dec_logvar_t.exp().sqrt())

            # recurrence: u_t+1, z_t -> h_t+1
            _, h = self.rnn(torch.cat([phi_u_t, phi_z_t], 1).unsqueeze(0), h)

            # computing the loss
            KLD = self.kld_gauss(enc_mean_t, enc_logvar_t, prior_mean_t, prior_logvar_t)
            # loss_pred = F.mse_loss(sample, y[t], reduction='sum')
            loss_pred = torch.sum(pred_dist.log_prob(y[:, :, t]))
            loss += - loss_pred + KLD

        return loss

    def generate(self, u):
        # get the batch size
        batch_size = u.shape[0]
        # length of the sequence to generate
        seq_len = u.shape[-1]

        # allocation
        sample = torch.zeros(batch_size, self.y_dim, seq_len)
        sample_mu = torch.zeros(batch_size, self.y_dim, seq_len)
        sample_sigma = torch.zeros(batch_size, self.y_dim, seq_len)

        h = torch.zeros(self.n_layers, batch_size, self.h_dim, device=self.device)

        # constant so can be outside of loop
        # prior: z_t ~ N(0,1) (for KLD loss)
        prior_mean_t = torch.zeros([batch_size, self.z_dim], device=self.device)
        prior_logvar_t = torch.zeros([batch_size, self.z_dim], device=self.device)

        # for all time steps
        for t in range(seq_len):
            # feature extraction: u_t+1
            phi_u_t = self.phi_u(u[:, :, t])  # .unsqueeze(0).type(torch.float))

            # sampling and reparameterization: get new z_t
            temp = tdist.Normal(prior_mean_t, prior_logvar_t.exp().sqrt())
            z_t = tdist.Normal.rsample(temp)
            # feature extraction: z_t
            phi_z_t = self.phi_z(z_t)

            # decoder: z_t, h_t -> y_t
            dec_t = self.dec(torch.cat([phi_z_t, h[-1]], 1))
            dec_mean_t = self.dec_mean(dec_t)
            dec_logvar_t = self.dec_logvar(dec_t)
            # store the samples
            temp = tdist.Normal(dec_mean_t, dec_logvar_t.exp().sqrt())
            sample[:, :, t] = tdist.Normal.rsample(temp)
            # store mean and std
            sample_mu[:, :, t] = dec_mean_t
            sample_sigma[:, :, t] = dec_logvar_t.exp().sqrt()

            # recurrence: u_t+1, z_t -> h_t+1
            _, h = self.rnn(torch.cat([phi_u_t, phi_z_t], 1).unsqueeze(0), h)

        return sample, sample_mu, sample_sigma

    @staticmethod
    def kld_gauss(mu_q, logvar_q, mu_p, logvar_p):
        # Goal: Minimize KL divergence between q_pi(z|xi) || p(z|xi)
        # This is equivalent to maximizing the ELBO: - D_KL(q_phi(z|xi) || p(z)) + Reconstruction term
        # This is equivalent to minimizing D_KL(q_phi(z|xi) || p(z))
        term1 = logvar_p - logvar_q - 1
        term2 = (torch.exp(logvar_q) + (mu_q - mu_p) ** 2) / torch.exp(logvar_p)
        kld = 0.5 * torch.sum(term1 + term2)

        return kld
