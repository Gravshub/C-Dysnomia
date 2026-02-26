// SPDX-License-Identifier: Affection
// Source: https://gist.github.com/as-helios/d5b91494a7bcce91e52d330512a6b941
// Modified constructor: removed address[] _snipeTokens param for CLI deploy compatibility.
// Use addToken() post-deploy to populate snipe targets.

pragma solidity ^0.8.28;

interface IERC20 {
    function allowance(address _owner, address _spender) external view returns (uint256);
    function balanceOf(address _owner) external view returns (uint256);
    function approve(address spender, uint256 value) external returns (bool);
    function transferFrom(address _sender, address _recipient, uint256 _value ) external returns (bool);
    function transfer(address _recipient, uint256 _value) external returns (bool);
}

interface ILAU {
    function Chat(string calldata text) external;
    function Withdraw(address token, uint256 amount) external;
    function Username() external view returns (string memory);
    function owner(address cOwner) external view returns (bool);
    function Saat(uint256 _s) external view returns (uint64);
    function mintToCap() external;
}

interface ISnipeToken {
    function Purchase(address token, uint256 amount) external;
}

contract DSS {
    address _owner;
    uint64 public multiplier;
    address[] public sniping;
    address public lau; ILAU LAU; IERC20 _LAU;
    address affection = 0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D;
    IERC20 Affection = IERC20(affection);

    constructor(address _lau, uint64 _multiplier) {
        multiplier = _multiplier;
        lau = _lau;
        LAU = ILAU(_lau);
        _LAU = IERC20(_lau);
        _owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != _owner)
            revert ("Unauthorized");
        _;
    }

    modifier checkAffection() {
        if (Affection.allowance(msg.sender, address(this)) < (countTargets() * 10 ** 18))
            revert ("Insufficient allowance");
        if (Affection.balanceOf(msg.sender) < (countTargets() * 10 ** 18))
            revert ("Insufficient balance");
        _;
    }

    function setLAU(address _lau) public onlyOwner {
        lau = _lau;
    }

    function Username() view public returns (string memory) {
        return LAU.Username();
    }

    function owner(address _o) view public returns (bool) {
        return LAU.owner(_o);
    }

    function Saat(uint256 _s) view public returns (uint64) {
        return LAU.Saat(_s);
    }

    function withdraw(address _token, uint256 _amount) public payable onlyOwner {
        IERC20(_token).transfer(msg.sender, _amount);
    }

    function setChatMultiplier(uint64 _multiplier) public onlyOwner {
        multiplier = _multiplier;
    }

    function countTargets() private view returns (uint256) {
        uint256 counter;
        for (uint256 i; i < sniping.length; i++)
            if (sniping[i] != address(0))
                counter++;
        return counter;
    }

    function snipe() private {
        for (uint256 i; i < sniping.length; i++) {
            if (sniping[i] == address(0))
                continue;
            IERC20 token = IERC20(sniping[i]);
            if (token.balanceOf(sniping[i]) >= 1 * 10 ** 18) {
                Affection.transferFrom(msg.sender, address(this), 1 * 10 ** 18);
                ISnipeToken(sniping[i]).Purchase(affection, 1 * 10 ** 18);
                token.transfer(msg.sender, 1 * 10 ** 18);
            }
        }
    }

    function addToken(address _token) public onlyOwner {
        if (_token == address(0))
            revert ("Invalid snipe token");
        if (Affection.allowance(msg.sender, _token) < (type(uint256).max / 2))
            Affection.approve(affection, type(uint256).max);
        removeToken(_token);
        sniping.push(_token);
    }

    function removeToken(address _token) public onlyOwner {
        for (uint256 i; i < sniping.length; i++) {
            if (sniping[i] == _token) {
                delete sniping[i];
                return;
            }
        }
    }

    function mintToCap() public onlyOwner {
        LAU.mintToCap();
    }

    function mintToSelf(uint64 _amount) public onlyOwner {
        for (uint64 i = 0; i < _amount; i++)
            LAU.mintToCap();
        LAU.Withdraw(lau, _amount*10**18);
        _LAU.transfer(msg.sender, _amount*10**18);
    }

    function chatAndSnipeWithMultiplier(string calldata _text) public onlyOwner checkAffection {
        chatAndClaimWithMultiplier(_text);
        snipe();
    }

    function chatAndSnipe(string calldata _text) public onlyOwner checkAffection {
        chatAndClaim(_text);
        snipe();
    }

    function chatAndClaimWithMultiplier(string calldata _text) public onlyOwner {
        LAU.Chat(_text);
        for (uint256 i = 0; i < multiplier; i++)
            LAU.mintToCap();
        LAU.Withdraw(lau, (1 + multiplier)*10**18);
        _LAU.transfer(msg.sender, (1 + multiplier)*10**18);
    }

    function chatAndClaim(string calldata _text) public onlyOwner {
        LAU.Chat(_text);
        LAU.Withdraw(lau, 1*10**18);
        _LAU.transfer(msg.sender, 1*10**18);
    }

    function Chat(string calldata _text) public onlyOwner {
        LAU.Chat(_text);
    }
}
