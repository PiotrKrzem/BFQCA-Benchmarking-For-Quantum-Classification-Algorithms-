import numpy as np
import struct

from typing import List,Tuple
from cowskit.algorithms import Algorithm
from cowskit.utils import get_shape_size, compute_categorical_crossentropy_loss, softmax
# from cowskit.utils import bin_to_float, float_to_bin
from cowskit.utils import bin_to_floatV2 as bin_to_float, float_to_binV2 as float_to_bin

from qiskit import QuantumCircuit, Aer, QuantumRegister, ClassicalRegister, transpile
from qiskit_aer import AerSimulator

class GeneticAlgorithm(Algorithm):
    def __init__(self) -> None:
        Algorithm.__init__(self)

        self.epochs = 10
        self.population = 1000
        self.best_performers_count = 10
        self.deep_layers = 2
        self.trained_network:List[np.ndarray] = []

    def train(self, X: np.ndarray, Y: np.ndarray) -> None:
        samples_count = X.shape[0]
        n_features = get_shape_size(X)
        n_classes = get_shape_size(Y)
        
        X = X.reshape((samples_count, n_features))
        Y = Y.reshape((samples_count, n_classes))

        networks = self.construct_starting_networks(n_features, n_classes)
        best_performers_priority_queue: List[List[np.ndarray]] = []
        best_performers: List[List[np.ndarray]] = []

        for epoch in range(self.epochs):
            # Evaluate all networks
            for network in networks:
                result = X.copy()
                for layer in network:
                    result = result @ layer
                    result = (result > 0) * result # relu activation
                
                result = softmax(result)
                loss = compute_categorical_crossentropy_loss(Y, result)
                best_performers_priority_queue.append((loss, network))

            # Get best performers
            best_performers_priority_queue.sort(key=lambda x:x[0])
            best_performers_priority_queue = best_performers_priority_queue[:self.best_performers_count]
            best_performers = list(map( lambda x:x[1], best_performers_priority_queue))
            

            if epoch == self.epochs - 1:
                break
            
            networks = self.construct_new_networks(best_performers, n_features, n_classes)
            best_performers_priority_queue.clear()
            best_performers.clear()
        
        self.trained_network = best_performers[0]

    def predict(self, X: np.ndarray) -> np.ndarray:
        Y = X.copy()
        for layer in self.trained_network:
            Y = Y @ layer
            Y = (Y > 0) * Y
        Y = softmax(Y)
        return Y

    def construct_new_networks(self, best_performers:List[List[np.ndarray]],neruons_per_layer:int, output_classes:int):

        probability_network = self.construct_bits_network(neruons_per_layer, output_classes)

        # get probabilities of each float-bit to be equal to 1
        for network_idx in range(self.best_performers_count):
            for layer_idx in range(self.deep_layers+1):
                layer = best_performers[network_idx][layer_idx]
                shape = layer.shape
                for x in range(shape[0]):
                    for y in range(shape[1]):
                        binary = float_to_bin(layer[x][y])
                        for i,b in enumerate(binary):
                            probability_network[layer_idx][x][y][i] += 1 if b == "1" else 0

        for layer_idx in range(self.deep_layers+1):
            probability_network[layer_idx] /= self.best_performers_count

        # generate new networks from probabilities
        new_networks = self.construct_empty_networks(neruons_per_layer, output_classes)
        for layer_idx in range(self.deep_layers+1):
            layer = probability_network[layer_idx]
            shape = layer.shape
            for x in range(shape[0]):
                for y in range(shape[1]):
                    probabilities_array = layer[x][y]
                    results = self.generate_quantum_population(probabilities_array)
                    for network_idx in range(self.population):
                        new_networks[network_idx][layer_idx][x][y] = results[network_idx]

        return new_networks

    def generate_quantum_population(self, probabilities_array: np.ndarray):
        backend = Aer.get_backend('aer_simulator')
        results = np.zeros((self.population), dtype=np.float32)

        def get_result(idx:int, probabilities_array: np.ndarray, backend:AerSimulator):
            quantum_circuit = QuantumCircuit()
            qr = QuantumRegister(8)
            cr = ClassicalRegister(8)
            quantum_circuit.add_register(qr)
            quantum_circuit.add_register(cr)

            for i in range(8):
                quantum_circuit.h(qr[i])
                quantum_circuit.rx(probabilities_array[idx+i], qr[i])
                quantum_circuit.measure(qr[i],cr[i])

            job = backend.run(quantum_circuit, shots = self.population, memory=True)

            return job.result().get_memory()

        first_8_bits  = get_result(0,  probabilities_array, backend)
        second_8_bits = get_result(8,  probabilities_array, backend)
        third_8_bits  = get_result(16, probabilities_array, backend)
        fourth_8_bits = get_result(24, probabilities_array, backend)

        for i in range(self.population):
            full_binary_float = first_8_bits[i]+second_8_bits[i]+third_8_bits[i]+fourth_8_bits[i]
            generated_float = bin_to_float(full_binary_float)
            results[i] = generated_float

        return results

    def construct_starting_networks(self, neruons_per_layer:int, output_classes:int) -> List[List[np.ndarray]]:
        starting_networks: List[List[np.ndarray]] = [[]]*self.population
        for i in range(self.population):
            network = [0]*(self.deep_layers+1)
            for d in range(self.deep_layers):
                network[d] = np.random.rand(neruons_per_layer, neruons_per_layer).astype(np.float32)
            network[self.deep_layers] = np.random.rand(neruons_per_layer, output_classes).astype(np.float32)
            starting_networks[i] = network

        return starting_networks

    def construct_empty_networks(self, neruons_per_layer:int, output_classes:int) -> List[List[np.ndarray]]:
        construct_empty_networks: List[List[np.ndarray]] = [[]]*self.population
        for i in range(self.population):
            network = [0]*(self.deep_layers+1)
            for d in range(self.deep_layers):
                network[d] = np.zeros((neruons_per_layer, neruons_per_layer))
            network[self.deep_layers] = np.zeros((neruons_per_layer, output_classes))
            construct_empty_networks[i] = network

        return construct_empty_networks

    def construct_bits_network(self, neruons_per_layer:int, output_classes:int) -> List[np.ndarray]:

        network = [0]*(self.deep_layers+1)
        for d in range(self.deep_layers):
            network[d] = np.zeros((neruons_per_layer, neruons_per_layer, 32), dtype=np.float32)
        network[self.deep_layers] = np.zeros((neruons_per_layer, output_classes, 32), dtype=np.float32)

        return network




