from torch.nn import functional as F

from libs.train.base_trainer import BaseTrainer
from libs.utils import get_model_state


class HintonTrainer(BaseTrainer):
    """ Hinton et al., Distilling the Knowledge in a Neural Network
        (https://arxiv.org/abs/1503.02531)
    """
    def __init__(self, opt, teacher, student, callback, checkpoint):
        super(HintonTrainer, self).__init__(opt, teacher, student, callback)

        # Optimizer
        self.optimizer = self._define_optimizer(self.student.parameters(), opt.train.optimizer or opt.train.s_optimizer)
        if checkpoint is not None:
            self.optimizer.load_state_dict(checkpoint['optimizer'])

        # Loss function
        T = opt.train.sim_loss.temperature
        def loss_fn(s_logits, t_logits):
            loss = F.kl_div(F.log_softmax(s_logits / T, dim=1),
                            F.softmax(t_logits / T, dim=1), reduction='batchmean')
            return loss
        self.similarity_loss = loss_fn

        # Schedulers
        last_epoch = -1 if checkpoint is None else checkpoint['begin_epoch']
        self.scheduler = self._define_scheduler(self.optimizer, opt.train.scheduler or opt.train.s_scheduler, last_epoch)

    def get_snapshot(self):
        return {
            'teacher': get_model_state(self.teacher),
            'student': get_model_state(self.student),
            'optimizer': self.optimizer.state_dict()
        }

    def train(self, epoch, step):
        self.student.train()
        self.teacher.eval()

        self.callback.begin_epoch(epoch, step, len(self.train_loader))
        for i, (inputs, targets) in enumerate(self.train_loader):
            step += 1
            batch_size = inputs.shape[0]

            inputs = inputs.to(self.device)

            t_outputs = self._teacher_inference(inputs)

            s_inputs = F.interpolate(inputs, scale_factor=(1.0, 0.5, 0.5), mode='nearest')
            s_outputs = self.student(s_inputs)

            loss = self.similarity_loss(s_outputs['logits'], t_outputs['logits'])

            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

            losses = {
                'Loss': loss.mean().item()
            }
            lrs = {
                'Opt': self.optimizer.param_groups[0]['lr'],
            }
            self.callback.end_iter(epoch, step, losses, lrs, batch_size)

        self.callback.end_epoch(epoch, step)
        return step

    def step_scheduler(self, epoch, metric):
        self.scheduler(epoch, metric)
